import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { readSse } from "./sse";

const apiUrl = import.meta.env.VITE_ASSISTANT_API_URL || "http://localhost:8000";

type Message = { role: "user" | "assistant"; text: string };

export default function App() {
  const [open, setOpen] = useState(true);
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [notice, setNotice] = useState(
    "Do not enter personal or confidential information.",
  );
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, streaming]);

  useEffect(() => {
    const allowed = (import.meta.env.VITE_PARENT_ORIGINS || "")
      .split(",")
      .map((value: string) => value.trim())
      .filter(Boolean);
    const handler = (event: MessageEvent) => {
      if (allowed.length && !allowed.includes(event.origin)) return;
      if (event.data?.type === "zit:close") setOpen(false);
      if (event.data?.type === "zit:open") setOpen(true);
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  async function send() {
    const cleaned = text.trim();
    if (!cleaned || streaming) return;
    setMessages((items) => [...items, { role: "user", text: cleaned }]);
    setText("");
    setStreaming(true);
    let answer = "";
    try {
      const response = await fetch(`${apiUrl}/api/v1/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: cleaned }),
      });
      await readSse(response, (frame) => {
        if (frame.event === "delta") {
          answer += String(frame.data.t || "");
          setMessages((items) => {
            const last = items.at(-1);
            if (last?.role === "assistant") {
              return [...items.slice(0, -1), { role: "assistant", text: answer }];
            }
            return [...items, { role: "assistant", text: answer }];
          });
        }
      });
    } catch {
      setMessages((items) => [
        ...items,
        { role: "assistant", text: "The assistant could not respond. Please try again." },
      ]);
    } finally {
      setStreaming(false);
    }
  }

  if (!open) return null;

  return (
    <main className="chat" aria-label="ZIT website assistant">
      <header>
        <strong>ZIT Assistant</strong>
        <button type="button" onClick={() => setOpen(false)} aria-label="Close chat">
          Close
        </button>
      </header>
      <p className="notice">{notice}</p>
      <section className="messages" aria-live="polite">
        {messages.map((message, index) => (
          <article className={message.role} key={index}>
            {message.role === "assistant" ? (
              <ReactMarkdown
                components={{
                  a: ({ href, children }) => (
                    <a href={href?.startsWith("javascript:") ? undefined : href} target="_blank" rel="noreferrer">
                      {children}
                    </a>
                  ),
                }}
              >
                {message.text}
              </ReactMarkdown>
            ) : (
              <span>{message.text}</span>
            )}
          </article>
        ))}
        <div ref={bottomRef} />
      </section>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <label htmlFor="chat-message">Message</label>
        <textarea
          id="chat-message"
          value={text}
          onChange={(event) => setText(event.target.value)}
          maxLength={500}
        />
        <button type="submit" disabled={streaming}>Send</button>
      </form>
    </main>
  );
}

import { Bot, Check, Copy, RotateCcw } from "lucide-react";
import { FeedbackButtons } from "./FeedbackButtons";
import { LinkButtons } from "./LinkButtons";
import { MarkdownContent } from "./MarkdownContent";
import type { ChatMessage } from "../state/types";

type Props = {
  message: ChatMessage;
  copiedMessageId: string | null;
  contactUrl: string;
  onFeedback(id: string, rating: -1 | 1): void;
  onCopy(id: string): void;
  onRetry(): void;
};

export function MessageItem({
  message,
  copiedMessageId,
  contactUrl,
  onFeedback,
  onCopy,
  onRetry,
}: Props) {
  const assistant = message.role === "assistant";
  return (
    <article
      className={`message-row ${assistant ? "message-row-assistant" : "message-row-user"}`}
      data-status={message.status}
      aria-label={assistant ? "Assistant response" : "Your message"}
    >
      {assistant && (
        <span className="message-avatar" aria-hidden="true">
          <Bot size={17} />
        </span>
      )}
      <div className={`message-bubble ${assistant ? "message-bubble-assistant" : "message-bubble-user"}`}>
        <MessageText assistant={assistant} message={message} />
        <MessageStatus contactUrl={contactUrl} message={message} onRetry={onRetry} />
        <MessageActions
          assistant={assistant}
          copiedMessageId={copiedMessageId}
          message={message}
          onCopy={onCopy}
          onFeedback={onFeedback}
        />
      </div>
    </article>
  );
}

function MessageText({
  assistant,
  message,
}: {
  assistant: boolean;
  message: ChatMessage;
}) {
  if (message.status === "streaming" && !message.text) {
    return (
      <span className="typing-indicator" aria-label="Assistant is preparing a response">
        <span />
        <span />
        <span />
      </span>
    );
  }
  return assistant
    ? <MarkdownContent content={message.text} />
    : <p className="plain-message">{message.text}</p>;
}

function MessageStatus({
  contactUrl,
  message,
  onRetry,
}: {
  contactUrl: string;
  message: ChatMessage;
  onRetry(): void;
}) {
  if (message.status === "streaming" && message.text) {
    return <span className="stream-caret" aria-hidden="true" />;
  }
  if (message.status === "stopped") return <p className="message-state">Stopped</p>;
  if (message.status === "incomplete") {
    return (
      <div className="message-state message-state-warning">
        <p>This answer may be incomplete.</p>
        <RetryButton label="Retry" onRetry={onRetry} />
      </div>
    );
  }
  if (message.status !== "error") return null;
  return (
    <div className="message-state message-state-warning">
      <p>I couldn’t finish that request. Please try again.</p>
      <RetryButton label="Try again" onRetry={onRetry} />
      {message.traceId && <small className="reference-id">Reference: {message.traceId}</small>}
      {contactUrl && (
        <a className="contact-link" href={contactUrl} rel="noopener noreferrer" target="_blank">
          Contact ZIT
        </a>
      )}
    </div>
  );
}

function RetryButton({ label, onRetry }: { label: string; onRetry(): void }) {
  return (
    <button className="text-action" onClick={onRetry} type="button">
      <RotateCcw aria-hidden="true" size={15} />
      {label}
    </button>
  );
}

function MessageActions({
  assistant,
  copiedMessageId,
  message,
  onCopy,
  onFeedback,
}: {
  assistant: boolean;
  copiedMessageId: string | null;
  message: ChatMessage;
  onCopy(id: string): void;
  onFeedback(id: string, rating: -1 | 1): void;
}) {
  if (!assistant || message.status !== "complete") return null;
  return (
    <>
      <LinkButtons meta={message.meta} />
      {message.degraded && (
        <p className="degraded-note">
          Showing a quick answer. For full details, contact admissions.
        </p>
      )}
      <div className="message-actions">
        <button
          aria-label="Copy response"
          className="icon-button"
          onClick={() => onCopy(message.id)}
          type="button"
        >
          {message.id === copiedMessageId
            ? <Check aria-hidden="true" size={18} />
            : <Copy aria-hidden="true" size={18} />}
        </button>
        {message.traceId && (
          <FeedbackButtons
            rating={message.rating}
            onRate={(rating) => onFeedback(message.id, rating)}
          />
        )}
      </div>
      {message.rating !== null && (
        <p className="feedback-thanks" aria-live="polite">Thanks for the feedback.</p>
      )}
    </>
  );
}

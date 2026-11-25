import { Minimize2, Plus, X } from "lucide-react";

type Props = {
  busy: boolean;
  hasMessages: boolean;
  onNewChat(): void;
  onMinimize(): void;
  onClose(): void;
};

export function ChatHeader({ busy, hasMessages, onNewChat, onMinimize, onClose }: Props) {
  return (
    <header className="chat-header">
      <div className="brand-lockup">
        <img alt="" className="brand-mark" src="/zit-mark.png" />
        <div>
          <strong>ZIT Assistant</strong>
          <span className="connection-status">
            <span className={`status-dot ${busy ? "status-dot-busy" : ""}`} />
            {busy ? "Busy right now" : "Online"}
          </span>
        </div>
      </div>
      <nav className="header-actions" aria-label="Chat controls">
        <button
          aria-label="Start a new chat"
          className="icon-button"
          disabled={!hasMessages}
          onClick={onNewChat}
          title="New chat"
          type="button"
        >
          <Plus aria-hidden="true" size={19} />
        </button>
        <button
          aria-label="Minimize chat"
          className="icon-button"
          onClick={onMinimize}
          type="button"
        >
          <Minimize2 aria-hidden="true" size={18} />
        </button>
        <button
          aria-label="Close chat"
          className="icon-button"
          onClick={onClose}
          type="button"
        >
          <X aria-hidden="true" size={20} />
        </button>
      </nav>
    </header>
  );
}

import { AlertCircle, ArrowDown, LoaderCircle, ShieldCheck } from "lucide-react";
import type { Ref } from "react";
import type { ApiConfig } from "../api/types";
import type { LayoutMode } from "../state/bridge";
import type { ChatMessage } from "../state/types";
import { ChatHeader } from "./ChatHeader";
import { Composer } from "./Composer";
import { MessageItem } from "./MessageItem";
import { StatusBanner } from "./StatusBanner";
import { SuggestionChips } from "./SuggestionChips";
import { TurnstileChallenge } from "./TurnstileChallenge";

type Props = {
  config: ApiConfig | null;
  configLoading: boolean;
  configFailed: boolean;
  offline: boolean;
  statusMessage: string;
  messageHint: string;
  remainingSeconds: number;
  busy: boolean;
  messages: ChatMessage[];
  mode: LayoutMode;
  draft: string;
  streaming: boolean;
  disabled: boolean;
  privacyDismissed: boolean;
  privacyNotice: string;
  privacyUrl: string;
  contactUrl: string;
  copiedMessageId: string | null;
  showJump: boolean;
  turnstileSiteKey: string;
  turnstileResetKey: number;
  messageListRef: Ref<HTMLDivElement>;
  announcement: string;
  onClose(): void;
  onMinimize(): void;
  onNewChat(): void;
  onRetryConfig(): void;
  onListScroll(): void;
  onJump(): void;
  onPrivacyDismiss(): void;
  onSuggest(question: string): void;
  onDraftChange(value: string): void;
  onSubmit(): void;
  onStop(): void;
  onFeedback(id: string, rating: -1 | 1): void;
  onCopy(id: string): void;
  onRetry(id: string): void;
  onTurnstileToken(token: string): void;
};

export function ChatPanel(props: Props) {
  const visibleMessages = props.messages.slice(-100);
  const maintenance = props.config?.maintenance_message ?? "";
  const privacy = props.config?.privacy_notice || props.privacyNotice;

  return (
    <section className="chat-panel" aria-label="ZIT Assistant" aria-modal="true" role="dialog">
      <ChatHeader
        busy={props.busy}
        hasMessages={props.messages.length > 0}
        onClose={props.onClose}
        onMinimize={props.onMinimize}
        onNewChat={props.onNewChat}
      />
      <StatusBanner offline={props.offline} message={maintenance || props.statusMessage} />
      {renderPanelContent(props, visibleMessages, maintenance, privacy)}
    </section>
  );
}

function renderPanelContent(
  props: Props,
  visibleMessages: ChatMessage[],
  maintenance: string,
  privacy: string,
) {
  if (props.configLoading) return <LoadingState />;
  if (props.configFailed) {
    return <ConfigErrorState contactUrl={props.contactUrl} onRetry={props.onRetryConfig} />;
  }
  if (!props.config?.enabled && !maintenance) {
    return <UnavailableState contactUrl={props.contactUrl} />;
  }
  return (
    <ActiveConversation
      announcement={props.announcement}
      contactUrl={props.contactUrl}
      copiedMessageId={props.copiedMessageId}
      disabled={props.disabled}
      draft={props.draft}
      maintenance={maintenance}
      messageHint={props.messageHint}
      messageListRef={props.messageListRef}
      messages={visibleMessages}
      mode={props.mode}
      onCopy={props.onCopy}
      onDraftChange={props.onDraftChange}
      onFeedback={props.onFeedback}
      onJump={props.onJump}
      onListScroll={props.onListScroll}
      onPrivacyDismiss={props.onPrivacyDismiss}
      onRetry={props.onRetry}
      onStop={props.onStop}
      onSubmit={props.onSubmit}
      onSuggest={props.onSuggest}
      onTurnstileToken={props.onTurnstileToken}
      privacy={privacy}
      privacyDismissed={props.privacyDismissed}
      privacyUrl={props.privacyUrl}
      remainingSeconds={props.remainingSeconds}
      showJump={props.showJump}
      streaming={props.streaming}
      turnstileResetKey={props.turnstileResetKey}
      turnstileSiteKey={props.turnstileSiteKey}
    />
  );
}

type ActiveProps = {
  announcement: string;
  contactUrl: string;
  copiedMessageId: string | null;
  disabled: boolean;
  draft: string;
  maintenance: string;
  messageHint: string;
  messageListRef: Ref<HTMLDivElement>;
  messages: ChatMessage[];
  mode: LayoutMode;
  onCopy(id: string): void;
  onDraftChange(value: string): void;
  onFeedback(id: string, rating: -1 | 1): void;
  onJump(): void;
  onListScroll(): void;
  onPrivacyDismiss(): void;
  onRetry(id: string): void;
  onStop(): void;
  onSubmit(): void;
  onSuggest(question: string): void;
  onTurnstileToken(token: string): void;
  privacy: string;
  privacyDismissed: boolean;
  privacyUrl: string;
  remainingSeconds: number;
  showJump: boolean;
  streaming: boolean;
  turnstileResetKey: number;
  turnstileSiteKey: string;
};

function ActiveConversation(props: ActiveProps) {
  return (
    <>
      {props.messages.length === 0 ? (
        <div className="welcome-content">
          <div className="welcome-mark"><ShieldCheck aria-hidden="true" size={25} /></div>
          <p className="eyebrow">WELCOME TO ZIT</p>
          <h1>{props.maintenance ? "We’ll be back soon." : "How can I help you today?"}</h1>
          <p className="welcome-copy">
            {props.maintenance
              ? props.maintenance
              : "Ask about courses, fees, applying, programmes, facilities, or how to contact us."}
          </p>
          {!props.maintenance && <SuggestionChips onSelect={props.onSuggest} />}
          {props.maintenance && props.contactUrl && (
            <a className="contact-link" href={props.contactUrl} rel="noopener noreferrer" target="_blank">
              Contact admissions
            </a>
          )}
        </div>
      ) : (
        <div className="message-list" onScroll={props.onListScroll} ref={props.messageListRef} aria-label="Conversation">
          {props.messages.map((message) => (
            <MessageItem
              contactUrl={props.contactUrl}
              copiedMessageId={props.copiedMessageId}
              key={message.id}
              message={message}
              onCopy={props.onCopy}
              onFeedback={props.onFeedback}
              onRetry={() => props.onRetry(message.id)}
            />
          ))}
          {props.showJump && (
            <button className="jump-latest" onClick={props.onJump} type="button">
              <ArrowDown aria-hidden="true" size={15} />
              Jump to latest
            </button>
          )}
          <div className="sr-only" aria-live="polite" aria-atomic="true">{props.announcement}</div>
        </div>
      )}
      {!props.privacyDismissed && props.messages.length === 0 && (
        <PrivacyCard
          notice={props.privacy}
          onDismiss={props.onPrivacyDismiss}
          privacyUrl={props.privacyUrl}
        />
      )}
      <TurnstileChallenge
        onToken={props.onTurnstileToken}
        resetKey={props.turnstileResetKey}
        siteKey={props.turnstileSiteKey}
      />
      <Composer
        disabled={props.disabled}
        mobile={props.mode === "mobile"}
        messageHint={props.messageHint}
        onChange={props.onDraftChange}
        onStop={props.onStop}
        onSubmit={props.onSubmit}
        remainingSeconds={props.remainingSeconds}
        streaming={props.streaming}
        value={props.draft}
      />
    </>
  );
}

function PrivacyCard({
  notice,
  onDismiss,
  privacyUrl,
}: {
  notice: string;
  onDismiss(): void;
  privacyUrl: string;
}) {
  return (
    <aside className="privacy-card">
      <ShieldCheck aria-hidden="true" size={18} />
      <p>{notice}</p>
      <button
        aria-label="Dismiss privacy notice"
        className="privacy-dismiss"
        onClick={onDismiss}
        type="button"
      >
        ×
      </button>
      {privacyUrl && (
        <a href={privacyUrl} rel="noopener noreferrer" target="_blank">Privacy</a>
      )}
    </aside>
  );
}

function LoadingState() {
  return (
    <div className="loading-state" aria-busy="true">
      <span className="loading-skeleton loading-title" />
      <span className="loading-skeleton loading-line" />
      <span className="loading-skeleton loading-line-short" />
      <LoaderCircle aria-hidden="true" className="loading-icon" size={20} />
    </div>
  );
}

function ConfigErrorState({
  contactUrl,
  onRetry,
}: {
  contactUrl: string;
  onRetry(): void;
}) {
  return (
    <div className="connection-error" role="alert">
      <AlertCircle aria-hidden="true" size={22} />
      <p>The assistant couldn’t connect. Check your connection and try again.</p>
      <button className="primary-button" onClick={onRetry} type="button">Try again</button>
      {contactUrl && <a className="contact-link" href={contactUrl} rel="noopener noreferrer" target="_blank">Contact ZIT</a>}
    </div>
  );
}

function UnavailableState({ contactUrl }: { contactUrl: string }) {
  return (
    <div className="connection-error" role="status">
      <p>The assistant is not available right now.</p>
      {contactUrl && <a className="contact-link" href={contactUrl} rel="noopener noreferrer" target="_blank">Contact ZIT</a>}
    </div>
  );
}

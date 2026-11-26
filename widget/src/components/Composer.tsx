import { Send, Square } from "lucide-react";
import { useEffect, useRef } from "react";
import type { ChangeEvent, KeyboardEvent } from "react";
import { setComposerHeight } from "../utils/cssVariables";

type Props = {
  value: string;
  disabled: boolean;
  mobile: boolean;
  streaming: boolean;
  remainingSeconds: number;
  messageHint: string;
  onChange(value: string): void;
  onSubmit(): void;
  onStop(): void;
};

export function Composer({
  value,
  disabled,
  mobile,
  streaming,
  remainingSeconds,
  messageHint,
  onChange,
  onSubmit,
  onStop,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) setComposerHeight(textareaRef.current);
  }, [textareaRef, value]);

  return (
    <div className="composer" role="group" aria-label="Message composer">
      <label className="sr-only" htmlFor="chat-message">Write a message</label>
      <textarea
        autoComplete="off"
        id="chat-message"
        maxLength={500}
        onChange={(event) => handleComposerChange(event, onChange)}
        onKeyDown={(event) => handleComposerKeyDown(event, onSubmit, mobile)}
        placeholder="Write a message..."
        ref={textareaRef}
        rows={1}
        value={value}
      />
      {value.length >= 400 && <CharacterCount length={value.length} />}
      <ComposerButton
        disabled={disabled}
        onSubmit={onSubmit}
        onStop={onStop}
        remainingSeconds={remainingSeconds}
        streaming={streaming}
        value={value}
      />
      <p className="composer-note">
        AI can make mistakes. Confirm fees and dates with admissions.
      </p>
      {messageHint && <p className="composer-hint" role="status">{messageHint}</p>}
    </div>
  );
}

function handleComposerKeyDown(
  event: KeyboardEvent<HTMLTextAreaElement>,
  onSubmit: () => void,
  mobile: boolean,
): void {
  if (event.key === "Enter" && !event.shiftKey && !mobile) {
    event.preventDefault();
    onSubmit();
  }
}

function handleComposerChange(
  event: ChangeEvent<HTMLTextAreaElement>,
  onChange: (value: string) => void,
): void {
  onChange(event.currentTarget.value);
  setComposerHeight(event.currentTarget);
}

function CharacterCount({ length }: { length: number }) {
  return <span className="character-count" aria-live="polite">{length} / 500</span>;
}

function ComposerButton({
  disabled,
  onSubmit,
  onStop,
  remainingSeconds,
  streaming,
  value,
}: {
  disabled: boolean;
  onSubmit(): void;
  onStop(): void;
  remainingSeconds: number;
  streaming: boolean;
  value: string;
}) {
  return (
    <button
      aria-label={streaming ? "Stop response" : "Send message"}
      className="send-button"
      disabled={streaming ? false : disabled || value.trim().length === 0}
      onClick={streaming ? onStop : onSubmit}
      type="button"
    >
      {streaming ? (
        <Square aria-hidden="true" size={17} />
      ) : remainingSeconds > 0 ? (
        `Wait ${remainingSeconds}s`
      ) : (
        <Send aria-hidden="true" size={18} />
      )}
    </button>
  );
}

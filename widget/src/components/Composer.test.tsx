import { flushSync } from "react-dom";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Composer } from "./Composer";

describe("Composer", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    flushSync(() => root.unmount());
    container.remove();
  });

  it("sends from a button without triggering native form submission", () => {
    const onSubmit = vi.fn();
    const nativeSubmit = vi.fn();
    container.addEventListener("submit", nativeSubmit);
    renderComposer(onSubmit);

    const sendButton = container.querySelector<HTMLButtonElement>(".send-button");
    if (!sendButton) throw new Error("The composer send button was not rendered.");
    sendButton.click();

    expect(onSubmit).toHaveBeenCalledOnce();
    expect(nativeSubmit).not.toHaveBeenCalled();
    expect(container.querySelector("form")).toBeNull();
  });

  it("sends on Enter on desktop without submitting a form", () => {
    const onSubmit = vi.fn();
    const nativeSubmit = vi.fn();
    container.addEventListener("submit", nativeSubmit);
    renderComposer(onSubmit);

    const textarea = container.querySelector<HTMLTextAreaElement>("textarea");
    if (!textarea) throw new Error("The composer textarea was not rendered.");
    const enter = new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      key: "Enter",
    });
    textarea.dispatchEvent(enter);

    expect(onSubmit).toHaveBeenCalledOnce();
    expect(enter.defaultPrevented).toBe(true);
    expect(nativeSubmit).not.toHaveBeenCalled();
  });

  function renderComposer(onSubmit: () => void): void {
    flushSync(() => {
      root.render(
        <Composer
          disabled={false}
          messageHint=""
          mobile={false}
          onChange={vi.fn()}
          onStop={vi.fn()}
          onSubmit={onSubmit}
          remainingSeconds={0}
          streaming={false}
          value="Hello"
        />,
      );
    });
  }
});

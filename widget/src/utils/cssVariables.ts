export function setComposerHeight(element: HTMLTextAreaElement): void {
  const measured = Number.parseFloat(window.getComputedStyle(element).lineHeight);
  const lineHeight = Number.isFinite(measured) ? measured : 24;
  const maxHeight = lineHeight * 4 + 8;
  const height = Math.min(Math.max(element.scrollHeight, lineHeight + 8), maxHeight);
  element.style.setProperty("--composer-height", `${height}px`);
}

export function setCssNumber(
  element: HTMLElement,
  property: "--frame-scale",
  value: number,
): void {
  element.style.setProperty(property, String(value));
}

export function setCssPixels(
  element: HTMLElement,
  property: "--frame-width" | "--frame-height",
  value: number,
): void {
  element.style.setProperty(property, `${value}px`);
}

import { describe, expect, it, vi } from "vitest";
import { connectParent } from "./bridge";

const parentOrigin = "https://school.example.invalid";
const allowedOrigins = [parentOrigin];

describe("connectParent", () => {
  it("validates layout mode and defaults older loader messages to desktop", () => {
    const onInit = vi.fn();
    const disconnect = connectParent(window, allowedOrigins, onInit);

    window.dispatchEvent(new MessageEvent("message", {
      data: {
        type: "zit:init",
        apiUrl: "https://api.example.invalid",
        mode: "mobile",
        privacyNotice: "Keep personal information private.",
      },
      origin: parentOrigin,
      source: window.parent,
    }));

    expect(onInit).toHaveBeenCalledWith({
      apiUrl: "https://api.example.invalid",
      mode: "mobile",
      privacyNotice: "Keep personal information private.",
      parentOrigin,
    });

    window.dispatchEvent(new MessageEvent("message", {
      data: {
        type: "zit:init",
        apiUrl: "https://api.example.invalid",
        mode: "unknown",
      },
      origin: parentOrigin,
      source: window.parent,
    }));
    expect(onInit).toHaveBeenCalledTimes(1);

    window.dispatchEvent(new MessageEvent("message", {
      data: {
        type: "zit:init",
        apiUrl: "https://api.example.invalid",
      },
      origin: parentOrigin,
      source: window.parent,
    }));
    expect(onInit).toHaveBeenLastCalledWith({
      apiUrl: "https://api.example.invalid",
      mode: "desktop",
      privacyNotice: "",
      parentOrigin,
    });
    disconnect();
  });
});

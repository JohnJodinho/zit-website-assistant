import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { setCssNumber, setCssPixels } from "../utils/cssVariables";
import "../styles/global.css";
import "../styles/playground.css";

type Device = {
  id: string;
  label: string;
  width: number;
  height: number;
};

const devices: Device[] = [
  { id: "phone", label: "Phone — 390 × 844", width: 390, height: 844 },
  { id: "small-phone", label: "Small phone — 320 × 568", width: 320, height: 568 },
  { id: "tablet", label: "Tablet — 768 × 1024", width: 768, height: 1024 },
  { id: "laptop", label: "Laptop — 1366 × 768", width: 1366, height: 768 },
  { id: "desktop", label: "Desktop — 1920 × 1080", width: 1920, height: 1080 },
  { id: "landscape-phone", label: "Landscape phone — 844 × 390", width: 844, height: 390 },
];

const mockStates = [
  ["normal", "Normal answer with links"],
  ["slow-first-word", "Slow first word"],
  ["long-answer", "Long answer with table and list"],
  ["error-after-text", "Error after partial text"],
  ["interrupted", "Stream ends without done"],
  ["rate-limited", "Rate limited (429)"],
  ["session-expired", "Session expires, then recovers"],
  ["disabled", "Assistant disabled"],
  ["maintenance", "Maintenance message"],
  ["busy-fallback", "Busy capacity fallback"],
  ["message-too-long", "Message too long (413)"],
  ["offline", "Offline"],
] as const;

function isMockState(value: string): value is (typeof mockStates)[number][0] {
  return mockStates.some(([state]) => state === value);
}

function Playground() {
  const [deviceId, setDeviceId] = useState("phone");
  const [backend, setBackend] = useState<"local" | "mock">("local");
  const [mockState, setMockState] = useState<(typeof mockStates)[number][0]>("normal");
  const stageRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const device = useMemo(
    () => devices.find((candidate) => candidate.id === deviceId),
    [deviceId],
  );
  const fullWindow = deviceId === "full-window";

  useEffect(() => {
    const stage = stageRef.current;
    const frame = frameRef.current;
    if (!stage || !frame || fullWindow || !device) return;
    const fitFrame = (): void => {
      const bounds = stage.getBoundingClientRect();
      const scale = Math.min(
        1,
        Math.max(0.1, (bounds.width - 24) / device.width),
        Math.max(0.1, (bounds.height - 24) / device.height),
      );
      setCssPixels(frame, "--frame-width", device.width);
      setCssPixels(frame, "--frame-height", device.height);
      setCssNumber(frame, "--frame-scale", scale);
    };
    fitFrame();
    window.addEventListener("resize", fitFrame);
    return () => window.removeEventListener("resize", fitFrame);
  }, [device, fullWindow]);

  const params = new URLSearchParams({ backend });
  if (backend === "mock" && import.meta.env.DEV) params.set("state", mockState);
  const parentUrl = `/parent.html?${params.toString()}`;
  const apiUrl = backend === "mock" && import.meta.env.DEV
    ? `${window.location.origin}/__mock-api/${mockState}`
    : import.meta.env.VITE_ASSISTANT_API_URL;
  const widgetUrl = import.meta.env.VITE_ASSISTANT_WIDGET_URL || window.location.origin;

  return (
    <main className="playground-shell">
      <header className="playground-header">
        <div>
          <p className="playground-eyebrow">ZIT ASSISTANT</p>
          <h1>Local playground</h1>
          <p>Try the real loader inside a sample school page before publishing it.</p>
        </div>
        <div className="playground-controls">
          <label>
            <span>Device size</span>
            <select
              onChange={(event) => setDeviceId(event.currentTarget.value)}
              value={deviceId}
            >
              {devices.map((option) => (
                <option key={option.id} value={option.id}>{option.label}</option>
              ))}
              <option value="full-window">Full window</option>
            </select>
          </label>
          <label>
            <span>Backend</span>
            <select
              disabled={!import.meta.env.DEV}
              onChange={(event) => setBackend(event.currentTarget.value === "mock" ? "mock" : "local")}
              value={backend}
            >
              <option value="local">Local backend</option>
              {import.meta.env.DEV && <option value="mock">Mock backend</option>}
            </select>
          </label>
          {backend === "mock" && import.meta.env.DEV && (
            <label>
              <span>Mock response</span>
              <select
                onChange={(event) => {
                  const value = event.currentTarget.value;
                  setMockState(isMockState(value) ? value : "normal");
                }}
                value={mockState}
              >
                {mockStates.map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
          )}
        </div>
      </header>
      <section className="playground-stage" ref={stageRef} aria-label="Widget preview">
        <div
          className="scaled-frame"
          data-full-window={fullWindow}
          ref={frameRef}
        >
          <iframe
            className="device-frame"
            src={parentUrl}
            title="ZIT school page and assistant preview"
          />
        </div>
      </section>
      <footer className="playground-footer">
        <p><strong>API:</strong> <code>{apiUrl}</code></p>
        <p><strong>Widget:</strong> <code>{widgetUrl}</code></p>
        {!import.meta.env.DEV && (
          <p>Mock responses are available only in the development playground.</p>
        )}
      </footer>
    </main>
  );
}

const rootElement = document.getElementById("playground-root");
if (!rootElement) throw new Error("The playground root element is missing.");
createRoot(rootElement).render(<Playground />);

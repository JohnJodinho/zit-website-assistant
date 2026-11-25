import { useEffect, useRef, useState } from "react";

type Props = {
  siteKey: string;
  resetKey: number;
  onToken(token: string): void;
};

export function TurnstileChallenge({ siteKey, resetKey, onToken }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const widgetIdRef = useRef<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    if (!siteKey || !containerRef.current) return;
    const renderChallenge = (): void => {
      if (!window.turnstile || !containerRef.current || widgetIdRef.current) return;
      widgetIdRef.current = window.turnstile.render(containerRef.current, {
        sitekey: siteKey,
        callback: onToken,
        "expired-callback": () => onToken(""),
        "error-callback": () => {
          onToken("");
          setUnavailable(true);
        },
      });
    };

    let script = document.querySelector<HTMLScriptElement>("script[data-zit-turnstile]");
    if (window.turnstile) {
      renderChallenge();
    } else if (script) {
      script.addEventListener("load", renderChallenge);
      script.addEventListener("error", markUnavailable);
    } else {
      script = document.createElement("script");
      script.dataset.zitTurnstile = "true";
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      script.async = true;
      script.defer = true;
      script.addEventListener("load", renderChallenge);
      script.addEventListener("error", markUnavailable);
      document.head.append(script);
    }

    function markUnavailable(): void {
      setUnavailable(true);
    }

    return () => {
      script?.removeEventListener("load", renderChallenge);
      script?.removeEventListener("error", markUnavailable);
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.reset(widgetIdRef.current);
      }
    };
  }, [onToken, siteKey]);

  useEffect(() => {
    if (resetKey > 0 && widgetIdRef.current && window.turnstile) {
      window.turnstile.reset(widgetIdRef.current);
      setUnavailable(false);
    }
  }, [resetKey]);

  if (!siteKey) return null;
  return (
    <div className="turnstile-wrap">
      <div aria-label="Security check" className="turnstile-challenge" ref={containerRef} />
      {unavailable && <p className="composer-hint">The security check is unavailable. Please try again later.</p>}
    </div>
  );
}

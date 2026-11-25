import { AlertCircle, WifiOff } from "lucide-react";

type Props = {
  offline: boolean;
  message: string;
};

export function StatusBanner({ offline, message }: Props) {
  if (!offline && !message) return null;
  return (
    <div className="status-banner" role="status">
      {offline ? (
        <>
          <WifiOff aria-hidden="true" size={17} />
          <span>You’re offline. Reconnect to chat.</span>
        </>
      ) : (
        <>
          <AlertCircle aria-hidden="true" size={17} />
          <span>{message}</span>
        </>
      )}
    </div>
  );
}

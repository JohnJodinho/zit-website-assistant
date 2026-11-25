import { ExternalLink } from "lucide-react";
import { isApiLink, type ChatMeta } from "../api/types";

type Props = {
  meta: ChatMeta | null;
};

export function LinkButtons({ meta }: Props) {
  if (!meta) return null;
  const links = Object.entries(meta.links).filter((entry) => isApiLink(entry[1]));
  if (links.length === 0) return null;

  return (
    <nav className="answer-links" aria-label="Related links">
      {links.map(([key, link]) => (
        <a
          className="answer-link"
          href={link.url}
          key={key}
          rel="noopener noreferrer"
          target="_blank"
        >
          {link.label}
          <ExternalLink aria-hidden="true" size={14} />
        </a>
      ))}
    </nav>
  );
}

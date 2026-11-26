import { ExternalLink } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { ComponentProps, ReactNode } from "react";
import type { ExtraProps } from "react-markdown";
import remarkGfm from "remark-gfm";
import { isHttpUrl } from "../api/types";

type Props = {
  content: string;
};

export function MarkdownContent({ content }: Props) {
  return (
    <div className="markdown-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={(url) => (isHttpUrl(url) ? url : "")}
        components={{ a: renderLink }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function renderLink({
  href,
  children,
}: ComponentProps<"a"> & ExtraProps) {
  if (!href || !isHttpUrl(href)) return <>{children}</>;
  return (
    <a
      className="markdown-link"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
    >
      {shortenAutolinkLabel(children, href)}
      <ExternalLink aria-hidden="true" size={14} />
    </a>
  );
}

function shortenAutolinkLabel(children: ReactNode, href: string): ReactNode {
  if (typeof children !== "string" || normalizeUrl(children) !== normalizeUrl(href)) {
    return children;
  }
  return children.replace(/^https?:\/\/(?:www\.)?/i, "").replace(/^www\./i, "");
}

function normalizeUrl(value: string): string {
  try {
    const url = new URL(value.startsWith("www.") ? `https://${value}` : value);
    return `${url.hostname.replace(/^www\./i, "")}${url.pathname.replace(/\/$/, "")}${url.search}${url.hash}`;
  } catch {
    return "";
  }
}

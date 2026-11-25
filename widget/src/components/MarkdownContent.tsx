import { ExternalLink } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { isHttpUrl } from "../api/types";

type Props = {
  content: string;
};

export function MarkdownContent({ content }: Props) {
  return (
    <div className="markdown-content">
      <ReactMarkdown
        urlTransform={(url) => (isHttpUrl(url) ? url : "")}
        components={{
          a: ({ href, children }) => (
            <a
              className="markdown-link"
              href={href && isHttpUrl(href) ? href : undefined}
              target="_blank"
              rel="noopener noreferrer"
            >
              {children}
              <ExternalLink aria-hidden="true" size={14} />
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

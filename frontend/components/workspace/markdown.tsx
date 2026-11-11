"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { prepareMarkdown } from "@/lib/citations";
import { cn } from "@/lib/utils";
import { CitationBadge } from "./citation-badge";

/** Markdown con badges de cita clicables ([[cite:id]] -> badge que abre el inspector de evidencia). */
export function Markdown({ markdown, className }: { markdown: string; className?: string }) {
  return (
    <div className={cn("memo", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            if (href?.startsWith("#cite-")) return <CitationBadge id={href.slice("#cite-".length)} />;
            return (
              <a href={href} target="_blank" rel="noreferrer" className="text-primary underline">
                {children}
              </a>
            );
          },
        }}
      >
        {prepareMarkdown(markdown)}
      </ReactMarkdown>
    </div>
  );
}

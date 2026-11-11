"use client";

import { FileText, NotebookPen, TriangleAlert } from "lucide-react";
import { shortDocName, shortPage } from "@/lib/format";
import type { SourceCitation } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useWorkspace } from "./workspace-context";

export function CitationBadge({ id, citation, className }: { id?: string; citation?: SourceCitation; className?: string }) {
  const { citationIndex, openCitations, inspector } = useWorkspace();
  const c = citation ?? (id ? citationIndex.get(id) : undefined);
  if (!c) {
    return (
      <span className="mx-0.5 inline-flex items-center gap-1 rounded border border-destructive/40 bg-destructive/5 px-1 text-[10px] text-destructive">
        <TriangleAlert className="h-3 w-3" /> cita no encontrada
      </span>
    );
  }
  const active = inspector?.citations[inspector.index]?.citation_id === c.citation_id;
  const analyst = c.document_id === "analyst_input";
  const Icon = analyst ? NotebookPen : FileText;
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        openCitations([c]);
      }}
      title={`“${c.exact_quote}”`}
      className={cn(
        "mx-0.5 inline-flex max-w-[16rem] items-center gap-1 rounded border px-1 py-px align-baseline text-[10.5px] font-medium leading-tight transition-colors",
        active ? "border-primary bg-primary text-primary-foreground" : "border-primary/25 bg-accent text-accent-foreground hover:border-primary/60",
        className,
      )}
    >
      <Icon className="h-3 w-3 shrink-0" />
      <span className="truncate">
        {analyst ? "Nota del analista" : `${shortDocName(c.document_name)} · ${shortPage(c.page_or_sheet)}`}
      </span>
    </button>
  );
}

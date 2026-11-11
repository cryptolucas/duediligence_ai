"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, FileSearch, FileSpreadsheet, FileText, NotebookPen, X } from "lucide-react";
import type { SourceCitation, SourceDocument } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { useWorkspace } from "./workspace-context";

const DOC_TYPE_LABEL: Record<SourceDocument["document_type"], string> = {
  FINANCIAL_STATEMENTS_PDF: "Estados financieros",
  TRIAL_BALANCE_XLSX: "Balance de prueba",
  CHAMBER_OF_COMMERCE_CERT: "Cámara de Comercio",
  TEASER: "Teaser",
  APPRAISAL: "Avalúo",
  OTHER: "Otro",
};

/** Busca la cita en el contenido tolerando diferencias de espacios (igual que el guardián del backend). */
function locate(content: string, quote: string): [number, number] | null {
  const exact = content.indexOf(quote);
  if (exact >= 0) return [exact, exact + quote.length];
  const escaped = quote
    .trim()
    .split(/\s+/)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("\\s+");
  if (!escaped) return null;
  const match = new RegExp(escaped, "i").exec(content);
  return match ? [match.index, match.index + match[0].length] : null;
}

function PageView({ content, quote }: { content: string; quote?: string }) {
  const markRef = useRef<HTMLElement>(null);
  const range = useMemo(() => (quote ? locate(content, quote) : null), [content, quote]);
  useEffect(() => {
    markRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [range, content]);
  if (!content.trim()) {
    return <p className="p-3 text-xs text-muted-foreground">Página sin texto extraíble (posiblemente escaneada).</p>;
  }
  return (
    <pre className="whitespace-pre-wrap break-words p-3 font-mono text-[11px] leading-relaxed text-foreground/90">
      {range ? (
        <>
          {content.slice(0, range[0])}
          <mark ref={markRef} className="rounded-sm bg-yellow-200 px-0.5 text-foreground ring-1 ring-yellow-400">
            {content.slice(range[0], range[1])}
          </mark>
          {content.slice(range[1])}
        </>
      ) : (
        content
      )}
    </pre>
  );
}

export function EvidenceInspector() {
  const { view, inspector, setInspector } = useWorkspace();
  const docs = view.dossier.documents;
  const [browse, setBrowse] = useState<{ docId: string; page: string } | null>(null);
  const active: SourceCitation | undefined = inspector?.citations[inspector.index];

  useEffect(() => {
    if (active && active.document_id !== "analyst_input") setBrowse({ docId: active.document_id, page: active.page_or_sheet });
  }, [active]);

  const current = browse ?? (docs[0] ? { docId: docs[0].document_id, page: docs[0].pages[0]?.page_or_sheet ?? "" } : null);
  const doc = docs.find((d) => d.document_id === current?.docId);
  const pageIdx = doc ? Math.max(0, doc.pages.findIndex((p) => p.page_or_sheet === current?.page)) : 0;
  const page = doc?.pages[pageIdx];
  const showingActive = active && doc && page && active.document_id === doc.document_id && active.page_or_sheet === page.page_or_sheet;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
        <div className="flex items-center gap-1.5 text-sm font-semibold">
          <FileSearch className="h-4 w-4 text-primary" /> Inspector de evidencia
        </div>
        {inspector && (
          <Button variant="ghost" size="icon" onClick={() => setInspector(null)} aria-label="Cerrar cita">
            <X />
          </Button>
        )}
      </div>

      {inspector && inspector.citations.length > 1 && (
        <div className="border-b px-3 py-1.5">
          <div className="mb-1 text-[11px] text-muted-foreground">
            {inspector.title ?? "Fuentes"} — {inspector.citations.length} citas
          </div>
          <div className="flex max-h-16 flex-wrap gap-1 overflow-y-auto">
            {inspector.citations.map((c, i) => (
              <button
                key={c.citation_id + i}
                onClick={() => setInspector({ ...inspector, index: i })}
                className={cn(
                  "rounded border px-1.5 py-0.5 text-[10.5px]",
                  i === inspector.index ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent",
                )}
                title={c.exact_quote}
              >
                {c.cell_or_line_ref ?? c.page_or_sheet}
              </button>
            ))}
          </div>
        </div>
      )}

      {active && (
        <div className="space-y-1.5 border-b bg-accent/40 px-3 py-2">
          {active.document_id === "analyst_input" ? (
            <div className="flex items-center gap-1.5 text-xs font-medium">
              <NotebookPen className="h-3.5 w-3.5" /> Nota del analista (ajuste manual)
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="font-medium">{active.document_name}</span>
              <Badge variant="outline">{active.page_or_sheet}</Badge>
              {active.cell_or_line_ref && <Badge variant="outline">{active.cell_or_line_ref}</Badge>}
              <Badge variant={active.confidence >= 0.9 ? "positive" : active.confidence >= 0.6 ? "medium" : "high"}>
                confianza {(active.confidence * 100).toFixed(0)} %
              </Badge>
            </div>
          )}
          <blockquote className="border-l-2 border-primary pl-2 text-xs italic">“{active.exact_quote}”</blockquote>
        </div>
      )}

      {docs.length > 0 && (
        <div className="flex items-center gap-1.5 border-b px-3 py-1.5">
          {doc?.file_format === "PDF" ? <FileText className="h-3.5 w-3.5 shrink-0" /> : <FileSpreadsheet className="h-3.5 w-3.5 shrink-0" />}
          <Select
            className="h-7 text-xs"
            value={current?.docId}
            onChange={(e) => {
              const d = docs.find((x) => x.document_id === e.target.value);
              setBrowse({ docId: e.target.value, page: d?.pages[0]?.page_or_sheet ?? "" });
            }}
            aria-label="Documento"
          >
            {docs.map((d) => (
              <option key={d.document_id} value={d.document_id}>
                {d.document_name} ({DOC_TYPE_LABEL[d.document_type]})
              </option>
            ))}
          </Select>
          {doc && (
            <div className="flex shrink-0 items-center gap-0.5">
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                disabled={pageIdx === 0}
                onClick={() => setBrowse({ docId: doc.document_id, page: doc.pages[pageIdx - 1].page_or_sheet })}
                aria-label="Página anterior"
              >
                <ChevronLeft />
              </Button>
              <span className="min-w-[5.5rem] text-center text-[11px] tabular-nums">{page?.page_or_sheet}</span>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                disabled={pageIdx >= doc.pages.length - 1}
                onClick={() => setBrowse({ docId: doc.document_id, page: doc.pages[pageIdx + 1].page_or_sheet })}
                aria-label="Página siguiente"
              >
                <ChevronRight />
              </Button>
            </div>
          )}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto bg-card">
        {page ? (
          <PageView content={page.content} quote={showingActive ? active?.exact_quote : undefined} />
        ) : (
          <p className="p-3 text-xs text-muted-foreground">Sin documentos.</p>
        )}
        {!inspector && (
          <p className="sticky bottom-0 border-t bg-muted/90 px-3 py-1.5 text-[11px] text-muted-foreground">
            Haga clic en una cita o en una cifra para ver aquí la fuente exacta resaltada.
          </p>
        )}
      </div>
    </div>
  );
}

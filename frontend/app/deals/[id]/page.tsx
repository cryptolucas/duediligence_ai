"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertTriangle, FileText, Loader2, ShieldAlert, SlidersHorizontal } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { buildCitationIndex } from "@/lib/citations";
import type { DisplayUnit } from "@/lib/format";
import type { DealView, JobStatus, RecalculateRequest, SourceCitation } from "@/lib/types";
import { ProcessingView } from "@/components/processing-view";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ChatPanel } from "@/components/workspace/chat-panel";
import { DealHeader } from "@/components/workspace/deal-header";
import { EvidenceInspector } from "@/components/workspace/evidence-inspector";
import { FinancialsTab } from "@/components/workspace/financials-tab";
import { MemoTab } from "@/components/workspace/memo-tab";
import { RedFlagsTab } from "@/components/workspace/redflags-tab";
import { type InspectorState, WorkspaceContext, type WorkspaceContextValue } from "@/components/workspace/workspace-context";

const DEFAULT_TRM = 4000;
const POLL_MS = 1500;

export default function DealWorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const [view, setView] = useState<DealView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [unit, setUnit] = useState<DisplayUnit>("COP_M");
  const [trm, setTrm] = useState(DEFAULT_TRM);
  const [inspector, setInspector] = useState<InspectorState | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastRecalcMs, setLastRecalcMs] = useState<number | null>(null);
  const [extraCitations, setExtraCitations] = useState<SourceCitation[]>([]);

  const [job, setJob] = useState<JobStatus | null>(null);

  // Si el deal sigue procesándose en segundo plano, se consulta su estado hasta que termine.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      try {
        const status = await api.getStatus(id);
        if (cancelled) return;
        if (status.status === "DONE") {
          const loaded = await api.getDeal(id);
          if (!cancelled) {
            setView(loaded);
            setJob(null);
          }
          return;
        }
        setJob(status);
        if (status.status !== "FAILED") timer = setTimeout(poll, POLL_MS);
      } catch (e) {
        if (!cancelled) setError((e as ApiError).message);
      }
    }
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [id]);

  const citationIndex = useMemo(
    () => (view ? buildCitationIndex(view.dossier, extraCitations) : new Map<string, SourceCitation>()),
    [view, extraCitations],
  );

  const openCitations = useCallback(
    (refs: (string | SourceCitation)[], title?: string) => {
      const resolved = refs
        .map((r) => (typeof r === "string" ? citationIndex.get(r) : r))
        .filter((c): c is SourceCitation => Boolean(c));
      if (resolved.length) setInspector({ citations: resolved, index: 0, title });
    },
    [citationIndex],
  );

  const recalc = useCallback(
    async (body: RecalculateRequest) => {
      if (!view) return false;
      setBusy(true);
      setActionError(null);
      const started = performance.now();
      try {
        const res = await api.recalculate(view.dossier.deal_id, body);
        setView((prev) =>
          prev
            ? {
                ...prev,
                dossier: { ...prev.dossier, ebitda_adjustments: res.ebitda_adjustments, red_flags: res.red_flags },
                financials: res.financials,
                memo_markdown: res.memo_markdown,
              }
            : prev,
        );
        setLastRecalcMs(performance.now() - started);
        return true;
      } catch (e) {
        setActionError((e as ApiError).message);
        return false;
      } finally {
        setBusy(false);
      }
    },
    [view],
  );

  const registerCitations = useCallback((citations: SourceCitation[]) => {
    setExtraCitations((prev) => [...prev, ...citations.filter((c) => !prev.some((p) => p.citation_id === c.citation_id))]);
  }, []);

  if (error) {
    return (
      <main className="mx-auto max-w-xl px-4 py-16 text-center">
        <AlertTriangle className="mx-auto mb-2 h-8 w-8 text-destructive" />
        <p className="mb-4 text-sm">{error}</p>
        <Button asChild variant="outline">
          <Link href="/">Volver a operaciones</Link>
        </Button>
      </main>
    );
  }
  if (!view && job) return <ProcessingView job={job} />;
  if (!view) {
    return (
      <main className="flex h-[calc(100vh-3rem)] items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Cargando expediente…
      </main>
    );
  }

  const ctx: WorkspaceContextValue = {
    view,
    citationIndex,
    unit,
    trm,
    setUnit,
    setTrm,
    inspector,
    setInspector,
    openCitations,
    recalc,
    busy,
    lastRecalcMs,
    registerCitations,
  };
  const activeFlags = view.dossier.red_flags.filter((f) => f.status === "ACTIVE").length;

  return (
    <WorkspaceContext.Provider value={ctx}>
      <main className="grid lg:h-[calc(100vh-3rem)] lg:grid-cols-[3fr_2fr]">
        <section className="min-h-0 overflow-y-auto border-r">
          <DealHeader />
          <div className="px-4 pb-10 pt-3">
            {actionError && (
              <p className="mb-3 flex items-start gap-1.5 rounded-md bg-destructive/5 p-2 text-sm text-destructive">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {actionError}
              </p>
            )}
            <Tabs defaultValue="memo">
              <TabsList>
                <TabsTrigger value="memo">
                  <FileText /> Memo de Comité
                </TabsTrigger>
                <TabsTrigger value="financials">
                  <SlidersHorizontal /> Financieros y sandbox de EBITDA
                </TabsTrigger>
                <TabsTrigger value="flags">
                  <ShieldAlert /> Red flags ({activeFlags}) e info faltante
                </TabsTrigger>
              </TabsList>
              <TabsContent value="memo">
                <MemoTab />
              </TabsContent>
              <TabsContent value="financials">
                <FinancialsTab />
              </TabsContent>
              <TabsContent value="flags">
                <RedFlagsTab />
              </TabsContent>
            </Tabs>
          </div>
        </section>
        <aside className="flex min-h-0 flex-col bg-muted/30 max-lg:h-[90vh]">
          <div className="min-h-0 flex-1 border-b">
            <EvidenceInspector />
          </div>
          <div className="min-h-0 flex-1">
            <ChatPanel />
          </div>
        </aside>
      </main>
    </WorkspaceContext.Provider>
  );
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Check, Circle, FileText, Loader2, X } from "lucide-react";
import type { JobStatus } from "@/lib/types";
import { MODE_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m} min ${s % 60} s` : `${s} s`;
}

/** Segundos transcurridos que avanzan en vivo entre sondeos al backend. */
function useLiveElapsed(job: JobStatus): number {
  const [now, setNow] = useState(() => Date.now());
  const running = job.status === "QUEUED" || job.status === "RUNNING";
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  if (!running) return job.elapsed_s;
  const created = new Date(job.created_at.endsWith("Z") || job.created_at.includes("+") ? job.created_at : `${job.created_at}Z`).getTime();
  return Math.max(job.elapsed_s, (now - created) / 1000);
}

function StepIcon({ state }: { state: JobStatus["steps"][number]["state"] }) {
  if (state === "done") return <Check className="h-3.5 w-3.5 text-white" />;
  if (state === "running") return <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />;
  if (state === "failed") return <X className="h-3.5 w-3.5 text-white" />;
  return <Circle className="h-2.5 w-2.5 text-muted-foreground" />;
}

export function ProcessingView({ job }: { job: JobStatus }) {
  const elapsed = useLiveElapsed(job);
  const failed = job.status === "FAILED";
  const events = [...job.events].reverse().slice(0, 12);
  const effectiveMode = job.effective_mode as keyof typeof MODE_LABEL;

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="text-base">{failed ? "El procesamiento falló" : "Procesando el expediente"}</CardTitle>
            <Badge variant="muted">{MODE_LABEL[effectiveMode] ?? job.effective_mode}</Badge>
          </div>
          <CardDescription>{job.mode_reason}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div>
            <div className="mb-1 flex justify-between text-xs text-muted-foreground">
              <span>{failed ? "Detenido" : job.current_message || "En cola"}</span>
              <span className="tabular-nums">
                {job.progress_pct} % · {formatElapsed(elapsed)} · {job.llm_calls} llamadas LLM
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={job.progress_pct} aria-valuemin={0} aria-valuemax={100}>
              <div
                className={cn("h-full rounded-full transition-all duration-500", failed ? "bg-destructive" : "bg-primary")}
                style={{ width: `${Math.max(job.progress_pct, failed ? 100 : 3)}%` }}
              />
            </div>
          </div>

          <ol className="space-y-2">
            {job.steps.map((step, i) => (
              <li key={step.node} className="flex items-center gap-3">
                <span
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border",
                    step.state === "done" && "border-positive bg-positive",
                    step.state === "failed" && "border-destructive bg-destructive",
                    step.state === "running" && "border-primary bg-accent",
                  )}
                >
                  <StepIcon state={step.state} />
                </span>
                <span className={cn("text-sm", step.state === "pending" && "text-muted-foreground", step.state === "running" && "font-medium")}>
                  {i + 1}. {step.label}
                </span>
                {step.node === "node_deterministic_financial_engine" && <Badge variant="outline">0 LLM</Badge>}
              </li>
            ))}
          </ol>

          {failed && job.error && (
            <div className="flex items-start gap-2 rounded-md bg-destructive/5 p-3 text-sm text-destructive">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{job.error}</span>
            </div>
          )}

          {job.document_names.length > 0 && (
            <div>
              <h3 className="mb-1 text-xs font-semibold text-muted-foreground">Documentos</h3>
              <ul className="flex flex-wrap gap-1.5">
                {job.document_names.map((name) => (
                  <li key={name} className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs">
                    <FileText className="h-3 w-3" /> {name}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {events.length > 0 && (
            <div>
              <h3 className="mb-1 text-xs font-semibold text-muted-foreground">Actividad reciente</h3>
              <ul className="max-h-56 space-y-1 overflow-y-auto rounded-md border bg-muted/30 p-2 font-mono text-[11px]">
                {events.map((e, i) => (
                  <li key={`${e.at}-${i}`} className={cn(e.type === "error" && "text-destructive")}>
                    <span className="text-muted-foreground">{new Date(e.at).toLocaleTimeString("es-CO")}</span> {e.message}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {failed ? (
            <Button asChild>
              <Link href="/deals/new">Volver a cargar documentos</Link>
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">
              Puede cerrar esta pestaña: el procesamiento continúa en el servidor y la operación aparecerá en la lista de inicio.
            </p>
          )}
        </CardContent>
      </Card>
    </main>
  );
}

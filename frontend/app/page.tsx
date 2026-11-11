"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, FolderOpen, Loader2, Plus } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { DealSummary, JobStatus } from "@/lib/types";
import { MODE_LABEL, moneyWithUnit } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export default function HomePage() {
  const [deals, setDeals] = useState<DealSummary[] | null>(null);
  const [jobs, setJobs] = useState<JobStatus[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let activeBefore = 0;
    async function refresh() {
      try {
        const [list, pending] = await Promise.all([api.listDeals(), api.listJobs()]);
        if (cancelled) return;
        setDeals(list);
        setJobs(pending);
        const active = pending.filter((j) => j.status === "QUEUED" || j.status === "RUNNING").length;
        // Mientras haya procesos en curso se refresca; al terminar uno aparece en la tabla.
        if (active > 0 || activeBefore > 0) timer = setTimeout(refresh, 3000);
        activeBefore = active;
      } catch (e) {
        if (!cancelled) setError((e as ApiError).message);
      }
    }
    refresh();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Operaciones</h1>
          <p className="text-sm text-muted-foreground">Expedientes de screening con cifras trazables y motor financiero determinista.</p>
        </div>
        <Button asChild>
          <Link href="/deals/new">
            <Plus /> Nueva operación
          </Link>
        </Button>
      </div>

      {error && (
        <Card className="mb-4 flex items-center gap-2 border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4" /> {error}
        </Card>
      )}

      {jobs.length > 0 && (
        <section className="mb-5 space-y-2">
          <h2 className="text-sm font-semibold">Procesamientos en curso o con error</h2>
          <div className="grid gap-2 md:grid-cols-2">
            {jobs.map((job) => {
              const failed = job.status === "FAILED";
              return (
                <Link key={job.deal_id} href={`/deals/${job.deal_id}`}>
                  <Card className={cn("space-y-2 p-3 transition-colors hover:bg-accent/40", failed && "border-destructive/40")}>
                    <div className="flex items-center justify-between gap-2 text-sm">
                      <span className="flex min-w-0 items-center gap-1.5 font-medium">
                        {failed ? (
                          <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" />
                        ) : (
                          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
                        )}
                        <span className="truncate">{job.document_names.join(", ") || job.deal_id}</span>
                      </span>
                      <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{failed ? "Error" : `${job.progress_pct} %`}</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn("h-full rounded-full", failed ? "bg-destructive" : "bg-primary")}
                        style={{ width: `${failed ? 100 : Math.max(job.progress_pct, 3)}%` }}
                      />
                    </div>
                    <p className="truncate text-xs text-muted-foreground">{failed ? job.error : job.current_message}</p>
                  </Card>
                </Link>
              );
            })}
          </div>
        </section>
      )}

      {deals === null && !error && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Cargando operaciones…
        </div>
      )}

      {deals?.length === 0 && (
        <Card className="flex flex-col items-center gap-3 p-10 text-center">
          <FolderOpen className="h-8 w-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Aún no hay operaciones. Cargue documentos o abra el caso demo.</p>
          <Button asChild>
            <Link href="/deals/new">Empezar</Link>
          </Button>
        </Card>
      )}

      {deals && deals.length > 0 && (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Empresa</th>
                <th className="px-3 py-2 font-medium">Modo</th>
                <th className="px-3 py-2 font-medium">Periodos</th>
                <th className="px-3 py-2 text-right font-medium">Ingresos</th>
                <th className="px-3 py-2 text-right font-medium">EBITDA ajustado</th>
                <th className="px-3 py-2 font-medium">Red flags</th>
                <th className="px-3 py-2 font-medium">Cuadre</th>
                <th className="px-3 py-2 font-medium">Actualizado</th>
              </tr>
            </thead>
            <tbody>
              {deals.map((d) => (
                <tr key={d.deal_id} className="border-t hover:bg-accent/40">
                  <td className="px-3 py-2">
                    <Link href={`/deals/${d.deal_id}`} className="font-medium text-primary hover:underline">
                      {d.company_name}
                    </Link>
                    <div className="text-xs text-muted-foreground">
                      NIT {d.nit} · CIIU {d.ciiu_code}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant="muted">{MODE_LABEL[d.llm_mode]}</Badge>
                  </td>
                  <td className="px-3 py-2 text-xs">{d.periods.join(", ")}</td>
                  <td className="num px-3 py-2">{moneyWithUnit(d.revenue_last_cop, "COP_M", 1)}</td>
                  <td className="num px-3 py-2">{moneyWithUnit(d.ebitda_adjusted_last_cop, "COP_M", 1)}</td>
                  <td className="px-3 py-2">
                    <div className="flex gap-1">
                      {d.red_flags_by_severity.CRITICAL_DEALBREAKER ? (
                        <Badge variant="critical">{d.red_flags_by_severity.CRITICAL_DEALBREAKER} crítico</Badge>
                      ) : null}
                      {d.red_flags_by_severity.HIGH ? <Badge variant="high">{d.red_flags_by_severity.HIGH} alto</Badge> : null}
                      {d.red_flags_by_severity.MEDIUM ? <Badge variant="medium">{d.red_flags_by_severity.MEDIUM} medio</Badge> : null}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    {d.all_balances_tie ? (
                      <CheckCircle2 className="h-4 w-4 text-positive" aria-label="Balances cuadrados" />
                    ) : (
                      <AlertTriangle className="h-4 w-4 text-destructive" aria-label="Descuadre" />
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">{new Date(d.updated_at).toLocaleString("es-CO")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </main>
  );
}

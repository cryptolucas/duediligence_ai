"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, FolderOpen, Loader2, Plus } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { DealSummary } from "@/lib/types";
import { MODE_LABEL, moneyWithUnit } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export default function HomePage() {
  const [deals, setDeals] = useState<DealSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listDeals()
      .then(setDeals)
      .catch((e: ApiError) => setError(e.message));
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

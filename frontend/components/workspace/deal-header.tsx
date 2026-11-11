"use client";

import { CheckCircle2, History, Loader2, TriangleAlert } from "lucide-react";
import { formatMultiple, formatPct, MODE_LABEL, moneyWithUnit } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useWorkspace } from "./workspace-context";

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "warn" | "bad" }) {
  return (
    <div className="min-w-0 rounded-md border bg-card px-3 py-2">
      <div className="truncate text-[11px] text-muted-foreground">{label}</div>
      <div className={cn("truncate text-base font-semibold tabular-nums", tone === "bad" && "text-destructive", tone === "warn" && "text-warning")}>
        {value}
      </div>
      {sub && <div className="truncate text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

export function DealHeader() {
  const { view, unit, setUnit, trm, setTrm, busy, lastRecalcMs } = useWorkspace();
  const { dossier, financials: f } = view;
  const last = f.income_statement[f.income_statement.length - 1];
  const lev = f.leverage[f.leverage.length - 1];
  const base = f.valuation.scenarios.find((s) => s.scenario === "BASE");
  const unbalanced = f.balance_sheet.filter((b) => !b.balance_check.is_balanced);
  const contingencyPct = f.contingencies.unprovisioned_pct_of_adjusted_ebitda;

  return (
    <div className="space-y-3 border-b bg-card/60 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-lg font-semibold tracking-tight">{dossier.company_name}</h1>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>NIT {dossier.nit}</span>
            <span>CIIU {dossier.ciiu_code}</span>
            <span>{dossier.city}</span>
            <Badge variant="muted">{MODE_LABEL[dossier.llm_mode]}</Badge>
            {unbalanced.length === 0 ? (
              <span className="inline-flex items-center gap-1 text-positive">
                <CheckCircle2 className="h-3.5 w-3.5" /> Activo = Pasivo + Patrimonio ({f.periods.join(", ")})
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-destructive">
                <TriangleAlert className="h-3.5 w-3.5" /> Descuadre en {unbalanced.map((b) => b.period).join(", ")}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-md border bg-card p-0.5 text-xs" role="group" aria-label="Unidades">
            {(["COP_M", "USD"] as const).map((u) => (
              <button
                key={u}
                onClick={() => setUnit(u)}
                className={cn("rounded px-2 py-1 font-medium", unit === u ? "bg-primary text-primary-foreground" : "text-muted-foreground")}
              >
                {u === "COP_M" ? "COP Millones" : "USD"}
              </button>
            ))}
          </div>
          {unit === "USD" && (
            <label className="flex items-center gap-1 text-xs text-muted-foreground" title="Tasa de cambio supuesta para presentación">
              TRM
              <Input
                type="number"
                min={1}
                value={trm}
                onChange={(e) => setTrm(Math.max(1, Number(e.target.value) || 1))}
                className="h-7 w-24 text-xs"
              />
            </label>
          )}
          <ProcessingLogDialog />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
        <Kpi label={`Ingresos ${last.period}`} value={moneyWithUnit(last.revenue.value_cop, unit, trm)} sub={`YoY ${formatPct(last.revenue_growth_yoy_pct)}`} />
        <Kpi
          label={`EBITDA ajustado ${last.period}`}
          value={moneyWithUnit(last.ebitda_adjusted_cop, unit, trm)}
          sub={`Margen ${formatPct(last.ebitda_adjusted_margin_pct)} · reportado ${moneyWithUnit(last.ebitda_reported_cop, unit, trm)}`}
        />
        <Kpi
          label="Deuda neta / EBITDA aj."
          value={formatMultiple(lev.net_debt_to_ebitda_adjusted)}
          sub={`Deuda neta ${moneyWithUnit(lev.net_financial_debt_cop, unit, trm)}`}
        />
        <Kpi label="Enterprise Value (base)" value={base ? moneyWithUnit(base.enterprise_value_cop, unit, trm) : "n/d"} sub={base ? `${formatMultiple(base.ev_ebitda_multiple)} EV/EBITDA` : f.valuation.message ?? ""} />
        <Kpi label="Equity Value (base)" value={base ? moneyWithUnit(base.equity_value_cop, unit, trm) : "n/d"} sub={f.valuation.sector_label ?? "Sin benchmark"} />
        <Kpi
          label="Contingencias sin provisión"
          value={moneyWithUnit(f.contingencies.unprovisioned_probable_or_possible_cop, unit, trm)}
          sub={`${formatPct(contingencyPct)} del EBITDA aj.`}
          tone={contingencyPct !== null && contingencyPct >= 25 ? "bad" : contingencyPct ? "warn" : undefined}
        />
      </div>
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <span className="h-1.5 w-1.5 rounded-full bg-positive" />}
        Motor determinista v{f.engine_version} · {f.llm_calls} llamadas a LLM en cálculos
        {lastRecalcMs !== null && ` · último recálculo ${lastRecalcMs.toFixed(0)} ms`}
      </div>
    </div>
  );
}

function ProcessingLogDialog() {
  const { view } = useWorkspace();
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <History /> Bitácora
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Bitácora del grafo de agentes</DialogTitle>
          <DialogDescription>{view.mode_reason}</DialogDescription>
        </DialogHeader>
        <ol className="space-y-2 text-sm">
          {view.processing_log.map((entry, i) => (
            <li key={i} className="rounded-md border p-2">
              <div className="flex flex-wrap items-center gap-2">
                <code className="text-xs font-semibold">{entry.node}</code>
                <Badge variant="muted">{entry.mode}</Badge>
                <span className="text-xs text-muted-foreground">
                  {entry.duration_ms} ms · {entry.llm_calls} llamadas LLM
                </span>
              </div>
              <p className="mt-1 text-xs">{entry.message}</p>
              {entry.notes && entry.notes.length > 0 && (
                <ul className="mt-1 list-disc pl-4 text-xs text-muted-foreground">
                  {entry.notes.map((n, j) => (
                    <li key={j}>{n}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      </DialogContent>
    </Dialog>
  );
}

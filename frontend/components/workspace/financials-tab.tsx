"use client";

import { useState } from "react";
import { CheckCircle2, Info, Plus, Trash2, TriangleAlert } from "lucide-react";
import { ADJ_CATEGORY_LABEL, formatDays, formatMoney, formatMultiple, formatPct, moneyWithUnit, unitLabel } from "@/lib/format";
import type { AdjustmentCategory, EbitdaAdjustment, FinancialEngineResult, TracedValue } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { CitationBadge } from "./citation-badge";
import { useWorkspace } from "./workspace-context";

type Kind = "money" | "pct" | "mult" | "days" | "ratio" | "check";
interface RowDef {
  label: string;
  kind: Kind;
  value: (p: string) => number | null | undefined;
  traced?: (p: string) => TracedValue;
  negate?: boolean;
  strong?: boolean;
  subtle?: boolean;
}

function byPeriod<T extends { period: string }>(rows: T[]) {
  return (p: string) => rows.find((r) => r.period === p) as T;
}

function FinancialTable({ title, rows, f }: { title: string; rows: RowDef[]; f: FinancialEngineResult }) {
  const { unit, trm, openCitations } = useWorkspace();
  const fmt = (kind: Kind, v: number | null | undefined, negate?: boolean) => {
    if (kind === "money") return formatMoney(v === null || v === undefined ? v : negate ? -v : v, unit, trm, { parens: true });
    if (kind === "pct") return formatPct(v);
    if (kind === "mult") return formatMultiple(v);
    if (kind === "ratio") return v === null || v === undefined ? "n/d" : v.toFixed(2).replace(".", ",");
    return formatDays(v);
  };
  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle>{title}</CardTitle>
        <CardDescription>Cifras en {unitLabel(unit)}. Haga clic en una cifra para ver sus fuentes.</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0 pb-2">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-xs text-muted-foreground">
              <th className="px-4 py-1.5 text-left font-medium">Concepto</th>
              {f.periods.map((p) => (
                <th key={p} className="px-4 py-1.5 text-right font-medium">
                  {p}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className={cn("border-b last:border-0", row.strong && "bg-muted/50 font-semibold")}>
                <td className={cn("px-4 py-1.5", row.subtle && "pl-7 text-xs text-muted-foreground")}>{row.label}</td>
                {f.periods.map((p) => {
                  if (row.kind === "check") {
                    const bal = f.balance_sheet.find((b) => b.period === p)!.balance_check;
                    return (
                      <td key={p} className="num px-4 py-1.5">
                        {bal.is_balanced ? (
                          <CheckCircle2 className="ml-auto h-4 w-4 text-positive" aria-label="Cuadra" />
                        ) : (
                          <span className="text-destructive">{formatMoney(bal.difference_cop, unit, trm)}</span>
                        )}
                      </td>
                    );
                  }
                  const traced = row.traced?.(p);
                  const value = traced ? traced.value_cop : row.value(p);
                  const text = fmt(row.kind, value, row.negate);
                  return (
                    <td key={p} className={cn("num px-4 py-1.5", row.subtle && "text-xs text-muted-foreground")}>
                      {traced && traced.source_citation_ids.length > 0 ? (
                        <button
                          className="rounded px-1 underline decoration-dotted decoration-primary/40 underline-offset-2 hover:bg-accent"
                          onClick={() => openCitations(traced.source_citation_ids, `${row.label} ${p}`)}
                          title={`${traced.source_citation_ids.length} fuente(s)`}
                        >
                          {text}
                        </button>
                      ) : (
                        text
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function statusBadge(adj: EbitdaAdjustment) {
  if (adj.status === "ACCEPTED") return <Badge variant="positive">Aceptado</Badge>;
  if (adj.status === "REJECTED") return <Badge variant="muted">Rechazado</Badge>;
  return <Badge variant="medium">Pendiente de revisión</Badge>;
}

function EbitdaSandbox() {
  const { view, unit, trm, recalc, busy } = useWorkspace();
  const f = view.financials;
  const [period, setPeriod] = useState(f.periods[f.periods.length - 1]);
  const bridge = f.ebitda_bridge.find((b) => b.period === period)!;
  const adjustments = view.dossier.ebitda_adjustments.filter((a) => a.period === period);
  const inc = f.income_statement.find((r) => r.period === period)!;

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-2 space-y-0">
        <div>
          <CardTitle>Puente de EBITDA interactivo</CardTitle>
          <CardDescription>Cada switch recalcula EBITDA ajustado, apalancamiento, valoración y memo con el motor determinista.</CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <Select value={period} onChange={(e) => setPeriod(e.target.value)} className="h-8 w-24 text-xs" aria-label="Periodo">
            {f.periods.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </Select>
          <ManualAdjustmentDialog defaultPeriod={period} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between rounded-md bg-muted px-3 py-2 text-sm">
          <span>EBITDA reportado {period}</span>
          <span className="font-semibold tabular-nums">{moneyWithUnit(bridge.ebitda_reported_cop, unit, trm)}</span>
        </div>
        {adjustments.length === 0 && (
          <p className="rounded-md border border-dashed p-3 text-center text-xs text-muted-foreground">
            No hay ajustes propuestos para {period}. Agregue uno manual si tiene soporte.
          </p>
        )}
        <ul className="space-y-2">
          {adjustments.map((adj) => (
            <li key={adj.id} className={cn("rounded-md border p-3 transition-opacity", adj.status !== "ACCEPTED" && "opacity-75")}>
              <div className="flex items-start gap-3">
                <Switch
                  checked={adj.status === "ACCEPTED"}
                  disabled={busy}
                  onCheckedChange={(checked) => recalc({ adjustment_statuses: { [adj.id]: checked ? "ACCEPTED" : "REJECTED" } })}
                  aria-label={`Aceptar ajuste ${adj.title}`}
                  className="mt-0.5"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-sm font-medium">{adj.title}</span>
                    {statusBadge(adj)}
                    <Badge variant="outline">{ADJ_CATEGORY_LABEL[adj.category]}</Badge>
                    {adj.origin === "ANALYST_MANUAL" && <Badge variant="secondary">Manual</Badge>}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{adj.rationale}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <CitationBadge citation={adj.citation} />
                    {adj.status === "PENDING_REVIEW" && (
                      <button className="text-xs text-primary hover:underline" disabled={busy} onClick={() => recalc({ adjustment_statuses: { [adj.id]: "REJECTED" } })}>
                        Rechazar
                      </button>
                    )}
                    {adj.status !== "PENDING_REVIEW" && (
                      <button
                        className="text-xs text-muted-foreground hover:underline"
                        disabled={busy}
                        onClick={() => recalc({ adjustment_statuses: { [adj.id]: "PENDING_REVIEW" } })}
                      >
                        Marcar pendiente
                      </button>
                    )}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className={cn("text-sm font-semibold tabular-nums", adj.amount_cop < 0 ? "text-destructive" : "text-positive")}>
                    {adj.amount_cop >= 0 ? "+" : ""}
                    {moneyWithUnit(adj.amount_cop, unit, trm)}
                  </span>
                  {adj.origin === "ANALYST_MANUAL" && (
                    <Button
                      variant="ghost"
                      size="icon"
                      disabled={busy}
                      onClick={() => recalc({ remove_adjustment_ids: [adj.id] })}
                      aria-label="Eliminar ajuste manual"
                    >
                      <Trash2 className="text-muted-foreground" />
                    </Button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
        <div className="space-y-1 rounded-md border bg-card px-3 py-2 text-sm">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>Ajustes aceptados</span>
            <span className="tabular-nums">{moneyWithUnit(bridge.total_accepted_adjustments_cop, unit, trm)}</span>
          </div>
          {bridge.total_pending_adjustments_cop !== 0 && (
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Pendientes (excluidos del cálculo)</span>
              <span className="tabular-nums">{moneyWithUnit(bridge.total_pending_adjustments_cop, unit, trm)}</span>
            </div>
          )}
          <div className="flex justify-between border-t pt-1 font-semibold">
            <span>EBITDA ajustado {period}</span>
            <span className="tabular-nums">
              {moneyWithUnit(bridge.ebitda_adjusted_cop, unit, trm)}{" "}
              <span className="text-xs font-normal text-muted-foreground">({formatPct(inc.ebitda_adjusted_margin_pct)})</span>
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ManualAdjustmentDialog({ defaultPeriod }: { defaultPeriod: string }) {
  const { view, recalc, busy } = useWorkspace();
  const docs = view.dossier.documents;
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    title: "",
    category: "OTHER" as AdjustmentCategory,
    period: defaultPeriod,
    amountM: "",
    rationale: "",
    docId: "",
    page: "",
    quote: "",
  });
  const [error, setError] = useState<string | null>(null);
  const doc = docs.find((d) => d.document_id === form.docId);

  async function submit() {
    const amount = Number(form.amountM.replace(",", "."));
    if (!form.title.trim() || !form.rationale.trim() || !Number.isFinite(amount) || amount === 0) {
      setError("Complete título, monto (distinto de cero) y justificación.");
      return;
    }
    setError(null);
    const ok = await recalc({
      manual_adjustments: [
        {
          title: form.title.trim(),
          category: form.category,
          period: form.period,
          amount_cop: Math.round(amount * 1_000_000),
          rationale: form.rationale.trim(),
          evidence: form.docId && form.quote.trim() ? { document_id: form.docId, page_or_sheet: form.page, exact_quote: form.quote.trim() } : null,
        },
      ],
    });
    if (ok) {
      setOpen(false);
      setForm({ ...form, title: "", amountM: "", rationale: "", quote: "" });
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) setForm((prev) => ({ ...prev, period: defaultPeriod }));
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <Plus /> Ajuste manual
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Agregar ajuste manual</DialogTitle>
          <DialogDescription>
            Positivo suma al EBITDA (add-back); negativo resta. Si cita un documento, la cita debe aparecer literalmente en él.
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <Label htmlFor="adj-title">Título</Label>
            <Input id="adj-title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </div>
          <div>
            <Label htmlFor="adj-cat">Categoría</Label>
            <Select id="adj-cat" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as AdjustmentCategory })}>
              {Object.entries(ADJ_CATEGORY_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label htmlFor="adj-period">Periodo</Label>
              <Select id="adj-period" value={form.period} onChange={(e) => setForm({ ...form, period: e.target.value })}>
                {view.financials.periods.map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="adj-amount">COP millones</Label>
              <Input id="adj-amount" inputMode="decimal" placeholder="120" value={form.amountM} onChange={(e) => setForm({ ...form, amountM: e.target.value })} />
            </div>
          </div>
          <div className="col-span-2">
            <Label htmlFor="adj-rat">Justificación</Label>
            <Textarea id="adj-rat" value={form.rationale} onChange={(e) => setForm({ ...form, rationale: e.target.value })} />
          </div>
          <div className="col-span-2 rounded-md border p-2">
            <p className="mb-2 text-xs font-medium text-muted-foreground">Fuente (opcional; sin ella la fuente es “Nota del analista”)</p>
            <div className="grid grid-cols-2 gap-2">
              <Select value={form.docId} onChange={(e) => setForm({ ...form, docId: e.target.value, page: docs.find((d) => d.document_id === e.target.value)?.pages[0]?.page_or_sheet ?? "" })} aria-label="Documento">
                <option value="">Sin documento</option>
                {docs.map((d) => (
                  <option key={d.document_id} value={d.document_id}>
                    {d.document_name}
                  </option>
                ))}
              </Select>
              <Select value={form.page} disabled={!doc} onChange={(e) => setForm({ ...form, page: e.target.value })} aria-label="Página u hoja">
                {doc?.pages.map((p) => (
                  <option key={p.page_or_sheet}>{p.page_or_sheet}</option>
                ))}
              </Select>
              <Textarea
                className="col-span-2"
                disabled={!doc}
                placeholder="Copie aquí el fragmento literal del documento"
                value={form.quote}
                onChange={(e) => setForm({ ...form, quote: e.target.value })}
              />
            </div>
          </div>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <Button onClick={submit} disabled={busy}>
          Agregar y recalcular
        </Button>
      </DialogContent>
    </Dialog>
  );
}

function ValuationCard() {
  const { view, unit, trm, openCitations } = useWorkspace();
  const f = view.financials;
  const v = f.valuation;
  const last = f.income_statement[f.income_statement.length - 1];
  const wc = f.working_capital[f.working_capital.length - 1];
  const lev = f.leverage[f.leverage.length - 1];
  const bench = v.sector_operating_benchmarks;
  const companyValues: Record<string, [string, number | null, (x: number | null) => string]> = {
    gross_margin_pct: ["Margen bruto", last.gross_margin_pct, (x) => formatPct(x)],
    ebitda_margin_pct: ["Margen EBITDA ajustado", last.ebitda_adjusted_margin_pct, (x) => formatPct(x)],
    revenue_growth_pct: ["Crecimiento de ingresos", last.revenue_growth_yoy_pct, (x) => formatPct(x)],
    dso_days: ["Días de cartera (DSO)", wc.dso_days, formatDays],
    dio_days: ["Días de inventario (DIO)", wc.dio_days, formatDays],
    dpo_days: ["Días de proveedores (DPO)", wc.dpo_days, formatDays],
    net_debt_to_ebitda: ["Deuda neta / EBITDA aj.", lev.net_debt_to_ebitda_adjusted, formatMultiple],
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle>Valoración por múltiplos sectoriales ({v.valuation_period})</CardTitle>
        <CardDescription>
          {v.sector_label ?? "Sin sector"} · CIIU {v.ciiu_code} · Benchmarks {v.benchmark_status === "REFERENCIAL_NO_OFICIAL" ? "referenciales (no oficiales)" : v.benchmark_status}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {v.status !== "OK" ? (
          <p className="flex items-center gap-1.5 text-sm text-warning">
            <TriangleAlert className="h-4 w-4" /> {v.message}
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr className="border-b">
                <th className="py-1.5 text-left font-medium">Escenario</th>
                <th className="py-1.5 text-right font-medium">EV/EBITDA</th>
                <th className="py-1.5 text-right font-medium">Enterprise Value</th>
                <th className="py-1.5 text-right font-medium">Deuda neta</th>
                <th className="py-1.5 text-right font-medium">Equity Value</th>
                <th className="py-1.5 text-right font-medium">EV/Ingresos</th>
              </tr>
            </thead>
            <tbody>
              {v.scenarios.map((s) => (
                <tr key={s.scenario} className={cn("border-b last:border-0", s.scenario === "BASE" && "bg-accent/60 font-medium")}>
                  <td className="py-1.5">
                    {s.scenario === "CONSERVADOR" ? "Conservador" : s.scenario === "BASE" ? "Base" : "Optimista"}{" "}
                    <span className="text-xs text-muted-foreground">({s.percentile})</span>
                  </td>
                  <td className="num py-1.5">{formatMultiple(s.ev_ebitda_multiple)}</td>
                  <td className="num py-1.5">{formatMoney(s.enterprise_value_cop, unit, trm)}</td>
                  <td className="num py-1.5">{formatMoney(s.net_financial_debt_cop, unit, trm)}</td>
                  <td className="num py-1.5 font-semibold">{formatMoney(s.equity_value_cop, unit, trm)}</td>
                  <td className="num py-1.5">{formatMultiple(s.implied_ev_revenue)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="rounded-md bg-muted/60 p-2 text-xs">
          Contingencias probables/posibles sin provisión:{" "}
          <button
            className="font-semibold underline decoration-dotted"
            onClick={() =>
              openCitations(
                view.dossier.corporate_profile.legal_proceedings.map((p) => p.citation),
                "Contingencias",
              )
            }
          >
            {moneyWithUnit(f.contingencies.unprovisioned_probable_or_possible_cop, unit, trm)}
          </button>{" "}
          ({formatPct(f.contingencies.unprovisioned_pct_of_adjusted_ebitda)} del EBITDA ajustado;{" "}
          {formatPct(f.contingencies.unprovisioned_pct_of_base_equity_value)} del Equity base). No se descuentan del Equity Value.
        </div>
        {Object.keys(bench).length > 0 && (
          <table className="w-full text-xs">
            <thead className="text-muted-foreground">
              <tr className="border-b">
                <th className="py-1 text-left font-medium">Empresa vs. sector</th>
                <th className="py-1 text-right font-medium">Empresa</th>
                <th className="py-1 text-right font-medium">P25</th>
                <th className="py-1 text-right font-medium">Mediana</th>
                <th className="py-1 text-right font-medium">P75</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(companyValues)
                .filter(([key]) => bench[key])
                .map(([key, [label, value, fmt]]) => (
                  <tr key={key} className="border-b last:border-0">
                    <td className="py-1">{label}</td>
                    <td className="num py-1 font-medium">{fmt(value)}</td>
                    <td className="num py-1 text-muted-foreground">{fmt(bench[key].p25)}</td>
                    <td className="num py-1 text-muted-foreground">{fmt(bench[key].median)}</td>
                    <td className="num py-1 text-muted-foreground">{fmt(bench[key].p75)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

function DataQuality() {
  const { view } = useWorkspace();
  const f = view.financials;
  const items = view.dossier.unreadable_or_unmapped_items;
  const warnings = f.warnings;
  if (warnings.length === 0 && items.length === 0 && view.dossier.pre_closing_trial_balance_periods.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Calidad de datos</CardTitle>
        <CardDescription>Lo que no se pudo leer o mapear con certeza se reporta aquí; nunca se imputa un valor.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 text-xs">
        {view.dossier.pre_closing_trial_balance_periods.length > 0 && (
          <p className="flex items-start gap-1.5">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
            Balances de prueba pre-cierre en {view.dossier.pre_closing_trial_balance_periods.join(", ")}: el motor suma el resultado del ejercicio al
            patrimonio para validar la ecuación contable.
          </p>
        )}
        {warnings.map((w, i) => (
          <p key={i} className="flex items-start gap-1.5">
            <TriangleAlert className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", w.code === "BALANCE_MISMATCH" ? "text-destructive" : "text-warning")} />
            {w.message}
          </p>
        ))}
        <ul className="divide-y rounded-md border">
          {items.map((u) => (
            <li key={u.id} className="space-y-1 p-2">
              <div className="font-medium">{u.description}</div>
              <div className="text-muted-foreground">{u.reason}</div>
              {u.citation && <CitationBadge citation={u.citation} />}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function FinancialsTab() {
  const { view } = useWorkspace();
  const f = view.financials;
  const inc = byPeriod(f.income_statement);
  const bal = byPeriod(f.balance_sheet);
  const wc = byPeriod(f.working_capital);
  const lev = byPeriod(f.leverage);
  const bridge = byPeriod(f.ebitda_bridge);

  const incomeRows: RowDef[] = [
    { label: "Ingresos operacionales", kind: "money", value: () => null, traced: (p) => inc(p).revenue, strong: true },
    { label: "Crecimiento YoY", kind: "pct", value: (p) => inc(p).revenue_growth_yoy_pct, subtle: true },
    { label: "Costo de ventas", kind: "money", value: () => null, traced: (p) => inc(p).cogs, negate: true },
    { label: "Utilidad bruta", kind: "money", value: (p) => inc(p).gross_profit_cop, strong: true },
    { label: "Margen bruto", kind: "pct", value: (p) => inc(p).gross_margin_pct, subtle: true },
    { label: "Gastos de administración y ventas", kind: "money", value: () => null, traced: (p) => inc(p).sga, negate: true },
    { label: "Otros ingresos / gastos operativos", kind: "money", value: () => null, traced: (p) => inc(p).other_operating_income_expense },
    { label: "EBITDA reportado", kind: "money", value: (p) => inc(p).ebitda_reported_cop, strong: true },
    { label: "Margen EBITDA reportado", kind: "pct", value: (p) => inc(p).ebitda_reported_margin_pct, subtle: true },
    { label: "Ajustes aceptados", kind: "money", value: (p) => bridge(p).total_accepted_adjustments_cop },
    { label: "EBITDA ajustado", kind: "money", value: (p) => inc(p).ebitda_adjusted_cop, strong: true },
    { label: "Margen EBITDA ajustado", kind: "pct", value: (p) => inc(p).ebitda_adjusted_margin_pct, subtle: true },
    { label: "Depreciación y amortización", kind: "money", value: () => null, traced: (p) => inc(p).depreciation_amortization, negate: true },
    { label: "EBIT", kind: "money", value: (p) => inc(p).ebit_cop },
    { label: "Gasto financiero neto", kind: "money", value: () => null, traced: (p) => inc(p).net_interest, negate: true },
    { label: "Impuesto de renta", kind: "money", value: () => null, traced: (p) => inc(p).taxes, negate: true },
    { label: "Utilidad neta", kind: "money", value: (p) => inc(p).net_income_cop, strong: true },
    { label: "Margen neto", kind: "pct", value: (p) => inc(p).net_margin_pct, subtle: true },
  ];
  const balanceRows: RowDef[] = [
    { label: "Efectivo", kind: "money", value: () => null, traced: (p) => bal(p).cash },
    { label: "Cuentas por cobrar comerciales", kind: "money", value: () => null, traced: (p) => bal(p).accounts_receivable },
    { label: "Inventarios", kind: "money", value: () => null, traced: (p) => bal(p).inventory },
    { label: "Otros activos corrientes", kind: "money", value: () => null, traced: (p) => bal(p).other_current_assets },
    { label: "PPE e intangibles (neto)", kind: "money", value: () => null, traced: (p) => bal(p).ppe_and_intangibles },
    { label: "Total activo", kind: "money", value: (p) => bal(p).total_assets_cop, strong: true },
    { label: "Proveedores", kind: "money", value: () => null, traced: (p) => bal(p).accounts_payable },
    { label: "Deuda financiera corto plazo", kind: "money", value: () => null, traced: (p) => bal(p).short_term_debt },
    { label: "Otros pasivos corrientes", kind: "money", value: () => null, traced: (p) => bal(p).other_current_liabilities },
    { label: "Deuda financiera largo plazo", kind: "money", value: () => null, traced: (p) => bal(p).long_term_debt },
    { label: "Total pasivo", kind: "money", value: (p) => bal(p).total_liabilities_cop, strong: true },
    { label: "Patrimonio", kind: "money", value: (p) => bal(p).balance_check.total_equity_cop, strong: true },
    { label: "Activo = Pasivo + Patrimonio", kind: "check", value: () => null, subtle: true },
  ];
  const wcRows: RowDef[] = [
    { label: "Capital de trabajo neto (CxC + Inv. − CxP)", kind: "money", value: (p) => wc(p).net_working_capital_cop, strong: true },
    { label: "% de ingresos", kind: "pct", value: (p) => wc(p).nwc_pct_of_revenue, subtle: true },
    { label: "Días de cartera (DSO)", kind: "days", value: (p) => wc(p).dso_days },
    { label: "Días de inventario (DIO)", kind: "days", value: (p) => wc(p).dio_days },
    { label: "Días de proveedores (DPO)", kind: "days", value: (p) => wc(p).dpo_days },
    { label: "Ciclo de conversión de caja", kind: "days", value: (p) => wc(p).cash_conversion_cycle_days },
    { label: "Razón corriente", kind: "ratio", value: (p) => wc(p).current_ratio },
    { label: "Deuda financiera bruta", kind: "money", value: (p) => lev(p).gross_financial_debt_cop },
    { label: "Deuda financiera neta", kind: "money", value: (p) => lev(p).net_financial_debt_cop, strong: true },
    { label: "Deuda neta / EBITDA reportado", kind: "mult", value: (p) => lev(p).net_debt_to_ebitda_reported },
    { label: "Deuda neta / EBITDA ajustado", kind: "mult", value: (p) => lev(p).net_debt_to_ebitda_adjusted, strong: true },
    { label: "Cobertura de intereses (EBITDA aj.)", kind: "mult", value: (p) => lev(p).interest_coverage_ebitda_adjusted },
  ];

  return (
    <div className="space-y-4">
      <EbitdaSandbox />
      <ValuationCard />
      <FinancialTable title="Estado de resultados" rows={incomeRows} f={f} />
      <FinancialTable title="Balance general" rows={balanceRows} f={f} />
      <FinancialTable title="Capital de trabajo y apalancamiento" rows={wcRows} f={f} />
      <DataQuality />
    </div>
  );
}

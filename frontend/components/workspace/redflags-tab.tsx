"use client";

import { useMemo, useState } from "react";
import { Check, ClipboardCopy, Eye, EyeOff, Mail, MessageCircle, ShieldAlert } from "lucide-react";
import { DOMAIN_LABEL, moneyWithUnit, SEVERITY_LABEL } from "@/lib/format";
import type { CitedFact, MissingInfoItem, RedFlagItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/input";
import { CitationBadge } from "./citation-badge";
import { useWorkspace } from "./workspace-context";

const SEVERITY_VARIANT = { CRITICAL_DEALBREAKER: "critical", HIGH: "high", MEDIUM: "medium" } as const;
const SEVERITY_BORDER = { CRITICAL_DEALBREAKER: "border-l-destructive", HIGH: "border-l-orange-500", MEDIUM: "border-l-amber-400" } as const;

function RedFlagCard({ flag }: { flag: RedFlagItem }) {
  const { recalc, busy } = useWorkspace();
  const dismissed = flag.status === "DISMISSED";
  return (
    <Card className={cn("border-l-4", SEVERITY_BORDER[flag.severity], dismissed && "opacity-60")}>
      <CardContent className="space-y-2 p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant={SEVERITY_VARIANT[flag.severity]}>{SEVERITY_LABEL[flag.severity]}</Badge>
            <Badge variant="outline">{DOMAIN_LABEL[flag.domain]}</Badge>
            {dismissed && <Badge variant="muted">Descartada por el analista</Badge>}
          </div>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => recalc({ red_flag_statuses: { [flag.id]: dismissed ? "ACTIVE" : "DISMISSED" } })}
          >
            {dismissed ? <Eye /> : <EyeOff />} {dismissed ? "Reactivar" : "Descartar"}
          </Button>
        </div>
        <h3 className={cn("text-sm font-semibold", dismissed && "line-through")}>{flag.title}</h3>
        <p className="text-sm leading-relaxed">
          <span className="font-medium text-destructive">Escéptico: </span>
          {flag.challenge_by_skeptic}
        </p>
        <p className="rounded-md bg-muted/70 p-2 text-sm">
          <span className="font-medium">Pregunta al empresario: </span>
          {flag.mitigation_question}
        </p>
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-xs text-muted-foreground">Evidencia:</span>
          {flag.citations.map((c) => (
            <CitationBadge key={c.citation_id} citation={c} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function buildRequestMessage(company: string, items: MissingInfoItem[]): string {
  const must = items.filter((i) => i.priority === "MUST_HAVE_FOR_IC");
  const nice = items.filter((i) => i.priority !== "MUST_HAVE_FOR_IC");
  const block = (list: MissingInfoItem[], start: number) =>
    list.map((i, n) => `${start + n}. ${i.requested_document_or_clarification}\n   ¿Para qué? ${i.why_it_matters_plain_spanish}`).join("\n\n");
  const parts = [
    `Hola, ¿cómo está? Muchas gracias por la información de ${company} que nos han compartido; nos ha permitido avanzar bastante en el análisis.`,
    "Para seguir adelante necesitamos su ayuda con algunos documentos y aclaraciones. Sabemos que reunir esto toma tiempo, así que se los listamos en orden de prioridad:",
  ];
  if (must.length) parts.push(`Lo más importante:\n\n${block(must, 1)}`);
  if (nice.length) parts.push(`Si es posible, también nos ayudaría:\n\n${block(nice, must.length + 1)}`);
  parts.push(
    "Si algún documento no existe o prefiere explicarlo en una llamada, no hay problema: díganos y lo coordinamos. Puede enviarlo directamente usted o su contador.",
    "¡Muchas gracias!",
  );
  return parts.join("\n\n");
}

function MissingInfoSection() {
  const { view } = useWorkspace();
  const items = view.dossier.missing_info;
  const [selected, setSelected] = useState<Set<string>>(() => new Set(items.map((i) => i.id)));
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [copied, setCopied] = useState(false);
  const chosen = useMemo(() => items.filter((i) => selected.has(i.id)), [items, selected]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(message);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-2 space-y-0">
        <div>
          <CardTitle>Información faltante</CardTitle>
          <CardDescription>Explicado en lenguaje sencillo para el empresario o su contador.</CardDescription>
        </div>
        <Button
          size="sm"
          disabled={chosen.length === 0}
          onClick={() => {
            setMessage(buildRequestMessage(view.dossier.company_name, chosen));
            setCopied(false);
            setOpen(true);
          }}
        >
          <ClipboardCopy /> Copiar solicitud para el empresario ({chosen.length})
        </Button>
      </CardHeader>
      <CardContent>
        <ul className="divide-y rounded-md border">
          {items.map((item) => (
            <li key={item.id} className="flex items-start gap-3 p-3">
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 accent-[hsl(var(--primary))]"
                checked={selected.has(item.id)}
                onChange={() => toggle(item.id)}
                aria-label={`Incluir ${item.requested_document_or_clarification}`}
              />
              <div className="min-w-0 flex-1 space-y-0.5">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant={item.priority === "MUST_HAVE_FOR_IC" ? "high" : "muted"}>
                    {item.priority === "MUST_HAVE_FOR_IC" ? "Imprescindible para Comité" : "Deseable"}
                  </Badge>
                  <span className="text-xs text-muted-foreground">{item.category}</span>
                </div>
                <p className="text-sm font-medium">{item.requested_document_or_clarification}</p>
                <p className="text-xs text-muted-foreground">{item.why_it_matters_plain_spanish}</p>
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Solicitud para el empresario</DialogTitle>
            <DialogDescription>Revise y ajuste el texto antes de enviarlo por WhatsApp o correo.</DialogDescription>
          </DialogHeader>
          <Textarea value={message} onChange={(e) => setMessage(e.target.value)} className="min-h-[320px] text-sm" />
          <div className="flex flex-wrap gap-2">
            <Button onClick={copy}>
              {copied ? <Check /> : <ClipboardCopy />} {copied ? "Copiado" : "Copiar texto"}
            </Button>
            <Button variant="outline" asChild>
              <a href={`https://wa.me/?text=${encodeURIComponent(message)}`} target="_blank" rel="noreferrer">
                <MessageCircle /> Abrir en WhatsApp
              </a>
            </Button>
            <Button variant="outline" asChild>
              <a href={`mailto:?subject=${encodeURIComponent(`Información pendiente — ${view.dossier.company_name}`)}&body=${encodeURIComponent(message)}`}>
                <Mail /> Abrir en correo
              </a>
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function FactRow({ fact }: { fact: CitedFact }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 border-b py-1.5 last:border-0">
      <span className="text-xs text-muted-foreground">{fact.label}</span>
      <span className="flex flex-wrap items-center justify-end gap-1 text-right text-sm">
        {fact.status === "MISSING_DATA" ? <Badge variant="medium">MISSING_DATA</Badge> : fact.value}
        {fact.status === "UNVERIFIED" && <Badge variant="muted">No verificado</Badge>}
        {fact.citation && <CitationBadge citation={fact.citation} />}
      </span>
    </div>
  );
}

function CorporateProfileSection() {
  const { view, unit, trm } = useWorkspace();
  const p = view.dossier.corporate_profile;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Perfil societario y contingencias</CardTitle>
        <CardDescription>Datos del certificado de Cámara de Comercio, notas y teaser, cada uno con su fuente.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2">
        <div>
          {[p.legal_name, p.nit, p.ciiu_primary, p.ciiu_secondary, p.domicile, p.incorporation, p.legal_representative, p.alternate_legal_representative].map(
            (f) => (
              <FactRow key={f.label} fact={f} />
            ),
          )}
        </div>
        <div className="space-y-3">
          <div>
            <h4 className="mb-1 text-xs font-semibold">Composición accionaria</h4>
            {p.shareholders.length === 0 ? (
              <Badge variant="medium">MISSING_DATA</Badge>
            ) : (
              <ul className="space-y-1 text-sm">
                {p.shareholders.map((s) => (
                  <li key={s.name} className="flex flex-wrap items-center justify-between gap-1">
                    <span>{s.name}</span>
                    <span className="flex items-center gap-1">
                      <span className="tabular-nums">{s.ownership_pct !== null ? `${s.ownership_pct} %` : "n/d"}</span>
                      {s.verification_status !== "VERIFIED" && <Badge variant="muted">No verificado</Badge>}
                      {s.citation && <CitationBadge citation={s.citation} />}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h4 className="mb-1 text-xs font-semibold">Límites estatutarios</h4>
            <ul className="space-y-1 text-xs">
              {p.statutory_limits.length === 0 && <li className="text-muted-foreground">Sin información.</li>}
              {p.statutory_limits.map((l) => (
                <li key={l.label}>
                  <span className="font-medium">{l.label}:</span> {l.value} {l.citation && <CitationBadge citation={l.citation} />}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="mb-1 text-xs font-semibold">Litigios y contingencias</h4>
            <ul className="space-y-1.5 text-xs">
              {p.legal_proceedings.length === 0 && <li className="text-muted-foreground">No se identificaron procesos.</li>}
              {p.legal_proceedings.map((l) => (
                <li key={l.id} className="rounded-md border p-2">
                  <div className="flex flex-wrap items-center gap-1">
                    <Badge variant="outline">{l.proceeding_type}</Badge>
                    <Badge variant={l.probability === "PROBABLE" ? "critical" : l.probability === "POSIBLE" ? "high" : "muted"}>{l.probability}</Badge>
                    <span className="font-medium">
                      {moneyWithUnit(l.claimed_amount_cop, unit, trm)} · provisión {moneyWithUnit(l.provisioned_amount_cop, unit, trm)}
                    </span>
                  </div>
                  <p className="mt-1">
                    {l.description} <CitationBadge citation={l.citation} />
                  </p>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function RedFlagsTab() {
  const { view } = useWorkspace();
  const flags = view.dossier.red_flags;
  const active = flags.filter((f) => f.status === "ACTIVE");
  const dismissed = flags.filter((f) => f.status === "DISMISSED");
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm">
        <ShieldAlert className="h-4 w-4 text-destructive" />
        <span className="font-medium">{active.length} red flags activas</span>
        {dismissed.length > 0 && <span className="text-muted-foreground">· {dismissed.length} descartadas</span>}
      </div>
      {flags.length === 0 && <p className="text-sm text-muted-foreground">El agente escéptico no levantó red flags.</p>}
      <div className="space-y-3">
        {[...active, ...dismissed].map((f) => (
          <RedFlagCard key={f.id} flag={f} />
        ))}
      </div>
      <MissingInfoSection />
      <CorporateProfileSection />
    </div>
  );
}

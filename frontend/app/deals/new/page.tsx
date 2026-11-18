"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  Cloud,
  HardDrive,
  Info,
  Loader2,
  PlayCircle,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { DocumentValidation, LlmStatus, UploadIssue, UploadRequirements, UploadSlotId, UploadSlotSpec } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { entryStatus, type FileEntry, SlotCard, slotState } from "@/components/upload/slot-card";

type Mode = "CLOUD_API" | "LOCAL_OLLAMA";

let counter = 0;
const newId = () => `f${Date.now().toString(36)}${(counter++).toString(36)}`;

/** Revisión inmediata en el navegador. Un formato válido en otra casilla se deja al servidor, que lo lee y sugiere dónde va. */
function clientValidation(file: File, spec: UploadSlotSpec, maxMb: number, knownExtensions: string[]): DocumentValidation | null {
  const ext = file.name.includes(".") ? `.${file.name.split(".").pop()!.toLowerCase()}` : "";
  const fail = (message: string, fix: string): DocumentValidation => ({
    file_name: file.name,
    slot: spec.id,
    status: "error",
    summary: "",
    periods: [],
    issues: [{ level: "error", message, fix }],
    suggested_slot: null,
  });
  if (!knownExtensions.includes(ext)) {
    const formats = spec.accepted_extensions.map((e) => e.slice(1).toUpperCase()).join(", ");
    const hints: Record<string, string> = {
      ".doc": "Guarde el documento de Word como .docx o expórtelo a PDF.",
      ".pptx": "Exporte la presentación a PDF.",
      ".ppt": "Exporte la presentación a PDF.",
      ".zip": "Descomprima el archivo y cargue los documentos uno por uno.",
      ".rar": "Descomprima el archivo y cargue los documentos uno por uno.",
    };
    const isImage = [".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff"].includes(ext);
    return fail(
      `Formato no admitido: ${ext || "sin extensión"}.`,
      isImage
        ? "Las fotos e imágenes no se pueden leer. Use el PDF digital del documento."
        : `${hints[ext] ?? ""} Formatos aceptados en «${spec.label}»: ${formats}.`.trim(),
    );
  }
  if (file.size === 0) return fail("El archivo está vacío (0 bytes).", "Vuelva a descargarlo o exportarlo y cárguelo de nuevo.");
  if (file.size > maxMb * 1024 * 1024)
    return fail(
      `El archivo pesa ${(file.size / 1024 / 1024).toFixed(1)} MB y el máximo es ${maxMb} MB.`,
      "Comprima el PDF (Imprimir → Guardar como PDF) o divídalo en partes.",
    );
  return null;
}

export default function NewDealPage() {
  const router = useRouter();
  const [req, setReq] = useState<UploadRequirements | null>(null);
  const [reqError, setReqError] = useState<string | null>(null);
  const [status, setStatus] = useState<LlmStatus | null>(null);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [mode, setMode] = useState<Mode>("CLOUD_API");
  const [hints, setHints] = useState({ company_name: "", nit: "", ciiu_code: "" });
  const [busy, setBusy] = useState<"demo" | "upload" | null>(null);
  const [error, setError] = useState<{ message: string; issues: UploadIssue[] } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadRequirements = useCallback(() => {
    setReqError(null);
    api.uploadRequirements().then(setReq).catch((e) => setReqError((e as ApiError).message));
    api.llmStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  useEffect(loadRequirements, [loadRequirements]);

  const specsById = useMemo(
    () => Object.fromEntries((req?.slots ?? []).map((s) => [s.id, s])) as Record<string, UploadSlotSpec>,
    [req],
  );
  const knownExtensions = useMemo(() => Array.from(new Set((req?.slots ?? []).flatMap((s) => s.accepted_extensions))), [req]);

  const validate = useCallback(async (id: string, file: File, slot: UploadSlotId) => {
    let result: DocumentValidation;
    try {
      result = await api.validateDocument(file, slot);
    } catch (e) {
      result = {
        file_name: file.name,
        slot,
        status: "error",
        summary: "",
        periods: [],
        issues: [{ level: "error", message: `No se pudo revisar el archivo: ${(e as ApiError).message}`, fix: "Quítelo y vuelva a cargarlo." }],
        suggested_slot: null,
      };
    }
    setEntries((prev) => prev.map((e) => (e.id === id && e.slot === slot ? { ...e, state: "checked", validation: result } : e)));
  }, []);

  function addFiles(slot: UploadSlotId, files: File[]) {
    if (!req || files.length === 0) return;
    const spec = specsById[slot];
    setNotice(null);
    setError(null);
    const current = entries.filter((e) => e.slot === slot).length;
    const room = spec.max_files - current;
    if (files.length > room) {
      setNotice(`«${spec.label}» admite máximo ${spec.max_files} archivo(s). Se agregaron solo los primeros ${Math.max(room, 0)}.`);
    }
    const added: FileEntry[] = [];
    for (const file of files.slice(0, Math.max(room, 0))) {
      const dup = [...entries, ...added].find((e) => e.file.name === file.name && e.file.size === file.size);
      if (dup) {
        setNotice(`«${file.name}» ya está cargado en «${specsById[dup.slot].label}».`);
        continue;
      }
      const local = clientValidation(file, spec, req.max_file_mb, knownExtensions);
      added.push({ id: newId(), file, slot, state: local ? "checked" : "validating", validation: local });
    }
    setEntries((prev) => [...prev, ...added]);
    added.filter((e) => e.state === "validating").forEach((e) => validate(e.id, e.file, slot));
  }

  function removeEntry(id: string) {
    setEntries((prev) => prev.filter((e) => e.id !== id));
    setError(null);
  }

  function moveEntry(id: string, slot: UploadSlotId) {
    const entry = entries.find((e) => e.id === id);
    if (!entry || !req) return;
    const spec = specsById[slot];
    if (entries.filter((e) => e.slot === slot).length >= spec.max_files) {
      setNotice(`«${spec.label}» ya tiene el máximo de archivos. Quite uno antes de mover este.`);
      return;
    }
    const local = clientValidation(entry.file, spec, req.max_file_mb, knownExtensions);
    setEntries((prev) => prev.map((e) => (e.id === id ? { ...e, slot, state: local ? "checked" : "validating", validation: local } : e)));
    if (!local) validate(id, entry.file, slot);
  }

  const bySlot = useMemo(() => {
    const out: Record<UploadSlotId, FileEntry[]> = { TRIAL_BALANCE: [], FINANCIAL_STATEMENTS: [], CHAMBER_CERTIFICATE: [], OTHER: [] };
    entries.forEach((e) => out[e.slot].push(e));
    return out;
  }, [entries]);

  const required = (req?.slots ?? []).filter((s) => s.required);
  const optional = (req?.slots ?? []).filter((s) => !s.required);
  const blockers: string[] = [];
  required.forEach((s) => {
    if (!bySlot[s.id].some((e) => ["valid", "warning"].includes(entryStatus(e)))) blockers.push(`Falta: ${s.label}`);
  });
  const withErrors = entries.filter((e) => entryStatus(e) === "error");
  if (withErrors.length) blockers.push(`Corrija o quite ${withErrors.length} archivo(s) con errores`);
  const validating = entries.filter((e) => entryStatus(e) === "validating").length;
  if (validating) blockers.push(`Revisando ${validating} archivo(s)…`);
  const canSubmit = req !== null && blockers.length === 0 && busy === null;

  async function openDemo() {
    setBusy("demo");
    setError(null);
    try {
      const view = await api.createDemo();
      router.push(`/deals/${view.dossier.deal_id}`);
    } catch (e) {
      setError({ message: (e as ApiError).message, issues: [] });
      setBusy(null);
    }
  }

  async function upload() {
    if (!canSubmit) return;
    setBusy("upload");
    setError(null);
    try {
      const files = Object.fromEntries(
        (Object.keys(bySlot) as UploadSlotId[]).map((slot) => [slot, bySlot[slot].map((e) => e.file)]),
      ) as Record<UploadSlotId, File[]>;
      const job = await api.uploadDeal(files, status?.ollama_available ? mode : "CLOUD_API", hints);
      router.push(`/deals/${job.deal_id}`);
    } catch (e) {
      const err = e as ApiError;
      // Los problemas de cada archivo se muestran junto al archivo.
      if (err.issues.length) {
        setEntries((prev) =>
          prev.map((entry) => {
            const own = err.issues.filter((i) => i.file === entry.file.name);
            if (!own.length) return entry;
            return {
              ...entry,
              state: "checked",
              validation: {
                file_name: entry.file.name,
                slot: entry.slot,
                status: "error",
                summary: entry.validation?.summary ?? "",
                periods: [],
                issues: own.map((i) => ({ level: "error" as const, message: i.message, fix: i.fix })),
                suggested_slot: null,
              },
            };
          }),
        );
      }
      setError({ message: err.message, issues: err.issues.filter((i) => !i.file) });
      setBusy(null);
    }
  }

  const aiNote = !status
    ? null
    : status.ollama_available && mode === "LOCAL_OLLAMA"
      ? `Modelo local en este equipo (${status.ollama_model}). Los documentos no salen del servidor. Puede tardar varios minutos por paso.`
      : status.cloud_available
        ? `Inteligencia artificial: ${status.cloud_label}${status.cloud_fallback_labels.length ? ` (respaldo: ${status.cloud_fallback_labels.join(", ")})` : ""}. Modelo abierto en un plan gratuito; las cifras siempre las calcula el motor determinista.`
        : "El servidor no tiene un modelo de IA configurado: el análisis se hará con reglas deterministas (cifras completas y red flags por reglas, sin ajustes de EBITDA automáticos).";

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Nueva operación</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Cargue los 3 documentos obligatorios de la empresa y, si quiere, otros archivos que complementen el análisis. Cada archivo se revisa
          al cargarlo: verá si es correcto o qué debe corregir.
        </p>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border bg-accent/40 p-4 sm:flex-row sm:items-center">
        <Info className="h-5 w-5 shrink-0 text-primary" />
        <div className="flex-1 text-sm">
          <p className="font-medium">¿Quiere ver primero cómo funciona?</p>
          <p className="text-muted-foreground">
            Abra un caso de ejemplo (Alimentos y Conservas del Oriente S.A.S., datos ficticios) con el resultado completo en segundos.
          </p>
        </div>
        <Button onClick={openDemo} disabled={busy !== null} variant="outline" className="shrink-0">
          {busy === "demo" ? <Loader2 className="animate-spin" /> : <PlayCircle />} Abrir caso demo
        </Button>
      </div>

      {!req && !reqError && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Cargando los requisitos…
        </div>
      )}
      {reqError && (
        <div className="flex flex-wrap items-center gap-2 rounded-md bg-destructive/5 p-3 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4" /> {reqError}
          <Button size="sm" variant="outline" onClick={loadRequirements}>
            <RefreshCw /> Reintentar
          </Button>
        </div>
      )}

      {req && (
        <>
          <section className="space-y-3">
            <div>
              <h2 className="text-base font-semibold">Paso 1 · Documentos obligatorios</h2>
              <p className="text-sm text-muted-foreground">Los tres son necesarios para iniciar el análisis. Cada uno va en su propia casilla.</p>
            </div>
            {required.map((spec) => (
              <SlotCard
                key={spec.id}
                spec={spec}
                entries={bySlot[spec.id]}
                specsById={specsById}
                maxFileMb={req.max_file_mb}
                onAdd={(files) => addFiles(spec.id, files)}
                onRemove={removeEntry}
                onMove={moveEntry}
                disabled={busy !== null}
              />
            ))}
          </section>

          <section className="space-y-3">
            <div>
              <h2 className="text-base font-semibold">Paso 2 · Otros archivos (opcionales)</h2>
              <p className="text-sm text-muted-foreground">
                Puede adjuntar cualquier documento adicional que considere útil para complementar la información y mejorar la calidad, precisión
                y profundidad del análisis. No son obligatorios: si no tiene ninguno, continúe al paso 3.
              </p>
            </div>
            {optional.map((spec) => (
              <SlotCard
                key={spec.id}
                spec={spec}
                entries={bySlot[spec.id]}
                specsById={specsById}
                maxFileMb={req.max_file_mb}
                onAdd={(files) => addFiles(spec.id, files)}
                onRemove={removeEntry}
                onMove={moveEntry}
                disabled={busy !== null}
              />
            ))}
          </section>

          <section className="space-y-4 rounded-lg border p-4">
            <h2 className="text-base font-semibold">Paso 3 · Generar el análisis</h2>

            {status?.ollama_available && (
              <div className="grid gap-2 sm:grid-cols-2">
                {(
                  [
                    { id: "CLOUD_API", icon: Cloud, title: "IA en la nube (gratuita)", sub: status.cloud_label ?? "Sin modelo configurado" },
                    { id: "LOCAL_OLLAMA", icon: HardDrive, title: "IA local (Ollama)", sub: "Confidencialidad estricta" },
                  ] as const
                ).map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setMode(opt.id)}
                    className={cn(
                      "flex items-start gap-2 rounded-md border p-2.5 text-left transition-colors",
                      mode === opt.id ? "border-primary bg-accent" : "hover:bg-muted/60",
                    )}
                  >
                    <opt.icon className="mt-0.5 h-4 w-4 text-primary" />
                    <span>
                      <span className="block text-sm font-medium">{opt.title}</span>
                      <span className="block text-xs text-muted-foreground">{opt.sub}</span>
                    </span>
                  </button>
                ))}
              </div>
            )}
            {aiNote && (
              <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
                {status?.cloud_available || mode === "LOCAL_OLLAMA" ? (
                  <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                ) : (
                  <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                )}
                {aiNote}
              </p>
            )}

            <details className="text-sm">
              <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
                Datos de la empresa (opcional: solo si el certificado no permite leerlos)
              </summary>
              <div className="mt-2 grid grid-cols-3 gap-2">
                <div className="col-span-3">
                  <Label htmlFor="company">Razón social</Label>
                  <Input id="company" value={hints.company_name} onChange={(e) => setHints({ ...hints, company_name: e.target.value })} />
                </div>
                <div className="col-span-2">
                  <Label htmlFor="nit">NIT</Label>
                  <Input id="nit" value={hints.nit} onChange={(e) => setHints({ ...hints, nit: e.target.value })} placeholder="900.000.000-0" />
                </div>
                <div>
                  <Label htmlFor="ciiu">CIIU</Label>
                  <Input id="ciiu" value={hints.ciiu_code} onChange={(e) => setHints({ ...hints, ciiu_code: e.target.value })} placeholder="1020" />
                </div>
              </div>
            </details>

            <ul className="space-y-1 text-sm" aria-label="Lista de verificación">
              {required.map((s) => {
                const state = slotState(bySlot[s.id]);
                const ok = bySlot[s.id].some((e) => ["valid", "warning"].includes(entryStatus(e))) && state !== "error";
                return (
                  <li key={s.id} className="flex items-center gap-2">
                    {ok ? (
                      <CheckCircle2 className="h-4 w-4 text-positive" />
                    ) : state === "error" ? (
                      <XCircle className="h-4 w-4 text-destructive" />
                    ) : state === "validating" ? (
                      <Loader2 className="h-4 w-4 animate-spin text-primary" />
                    ) : (
                      <Circle className="h-4 w-4 text-muted-foreground" />
                    )}
                    <span className={cn(!ok && "text-muted-foreground")}>{s.label}</span>
                  </li>
                );
              })}
              <li className="flex items-center gap-2 text-muted-foreground">
                <Circle className="h-4 w-4 opacity-0" />
                Otros archivos: {bySlot.OTHER.length ? `${bySlot.OTHER.length} cargado(s)` : "ninguno (opcional)"}
              </li>
            </ul>

            {notice && (
              <p className="flex items-start gap-1.5 rounded-md bg-amber-50 p-2 text-sm text-amber-900">
                <Info className="mt-0.5 h-4 w-4 shrink-0" /> {notice}
              </p>
            )}
            {error && (
              <div className="rounded-md bg-destructive/5 p-3 text-sm text-destructive">
                <p className="flex items-start gap-1.5 font-medium">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error.message}
                </p>
                {error.issues.length > 0 && (
                  <ul className="mt-1 list-disc space-y-0.5 pl-6">
                    {error.issues.map((i, n) => (
                      <li key={n}>
                        {i.message} {i.fix && <span className="text-muted-foreground">{i.fix}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            <Button onClick={upload} disabled={!canSubmit} size="lg" className="w-full">
              {busy === "upload" ? <Loader2 className="animate-spin" /> : <Sparkles />}
              {busy === "upload" ? "Enviando y validando los documentos…" : "Generar expediente"}
            </Button>
            {blockers.length > 0 ? (
              <p className="text-center text-xs text-muted-foreground">Para continuar: {blockers.join(" · ")}.</p>
            ) : (
              <p className="text-center text-xs text-muted-foreground">
                El análisis tarda normalmente entre 2 y 8 minutos. Verá el avance paso a paso y puede cerrar la pestaña: el resultado quedará en
                «Operaciones» de este navegador.
              </p>
            )}
          </section>
        </>
      )}
    </main>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Cloud, FileSpreadsheet, FileText, HardDrive, Loader2, PlayCircle, ShieldCheck, Upload, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { LlmStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";

const ACCEPTED = [".pdf", ".xlsx", ".xlsm", ".csv"];

type Mode = "CLOUD_API" | "LOCAL_OLLAMA";

export default function NewDealPage() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [mode, setMode] = useState<Mode>("CLOUD_API");
  const [hints, setHints] = useState({ company_name: "", nit: "", ciiu_code: "" });
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState<"demo" | "upload" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<LlmStatus | null>(null);

  useEffect(() => {
    api.llmStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  function addFiles(list: FileList | null) {
    if (!list) return;
    const incoming = Array.from(list);
    const rejected = incoming.filter((f) => !ACCEPTED.some((ext) => f.name.toLowerCase().endsWith(ext)));
    setError(rejected.length ? `Formato no soportado: ${rejected.map((f) => f.name).join(", ")}. Use PDF, XLSX o CSV.` : null);
    const valid = incoming.filter((f) => !rejected.includes(f));
    setFiles((prev) => [...prev, ...valid.filter((f) => !prev.some((p) => p.name === f.name && p.size === f.size))]);
  }

  async function openDemo() {
    setBusy("demo");
    setError(null);
    try {
      const view = await api.createDemo();
      router.push(`/deals/${view.dossier.deal_id}`);
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(null);
    }
  }

  async function upload() {
    setBusy("upload");
    setError(null);
    try {
      const job = await api.uploadDeal(files, mode, hints);
      router.push(`/deals/${job.deal_id}`);
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(null);
    }
  }

  const modeNote =
    status === null
      ? null
      : mode === "CLOUD_API"
        ? status.cloud_available
          ? `Se usará ${status.cloud_model}.`
          : "No hay API key configurada en backend/.env: los documentos se procesarán con reglas deterministas (sin LLM)."
        : status.ollama_available
          ? `Ollama responde en ${status.ollama_base_url} (${status.ollama_model}).`
          : `Ollama no responde en ${status.ollama_base_url}. Por confidencialidad no se usará la nube: se procesará con reglas deterministas.`;

  return (
    <main className="mx-auto grid max-w-5xl gap-5 px-4 py-8 lg:grid-cols-[2fr_3fr]">
      <div className="lg:col-span-2">
        <h1 className="text-xl font-semibold tracking-tight">Nueva operación</h1>
        <p className="text-sm text-muted-foreground">
          Cargue estados financieros (PDF), balances de prueba de Siigo/World Office (XLSX/CSV), certificado de Cámara de Comercio y teaser.
        </p>
      </div>

      <Card className="flex flex-col">
        <CardHeader>
          <CardTitle>Caso demo realista</CardTitle>
          <CardDescription>Alimentos y Conservas del Oriente S.A.S. — 6 documentos sintéticos, ~COP 28.000 millones de ventas.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-1 flex-col justify-between gap-4">
          <ul className="space-y-1 text-xs text-muted-foreground">
            <li>• Ajustes por sueldos de familiares, arriendo al socio y honorarios legales.</li>
            <li>• Litigio laboral y requerimiento DIAN sin provisión.</li>
            <li>• Cliente en reorganización y covenant bancario.</li>
          </ul>
          <Button onClick={openDemo} disabled={busy !== null} size="lg" className="w-full">
            {busy === "demo" ? <Loader2 className="animate-spin" /> : <PlayCircle />}
            Abrir caso demo en 1 clic
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Documentos propios</CardTitle>
          <CardDescription>Cada operación se procesa aislada en su propia carpeta y registro.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div
            role="button"
            tabIndex={0}
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              addFiles(e.dataTransfer.files);
            }}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-6 text-center transition-colors",
              dragging ? "border-primary bg-accent" : "border-input hover:bg-muted/60",
            )}
          >
            <Upload className="h-6 w-6 text-muted-foreground" />
            <p className="text-sm font-medium">Arrastre archivos aquí o haga clic para seleccionar</p>
            <p className="text-xs text-muted-foreground">PDF, XLSX o CSV · máx. 25 MB por archivo</p>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={ACCEPTED.join(",")}
              className="hidden"
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          {files.length > 0 && (
            <ul className="divide-y rounded-md border text-sm">
              {files.map((f) => (
                <li key={f.name + f.size} className="flex items-center gap-2 px-3 py-1.5">
                  {f.name.toLowerCase().endsWith(".pdf") ? (
                    <FileText className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <FileSpreadsheet className="h-4 w-4 text-muted-foreground" />
                  )}
                  <span className="flex-1 truncate">{f.name}</span>
                  <span className="text-xs text-muted-foreground">{(f.size / 1024).toFixed(0)} KB</span>
                  <button
                    onClick={() => setFiles((prev) => prev.filter((p) => p !== f))}
                    className="rounded p-0.5 hover:bg-muted"
                    aria-label={`Quitar ${f.name}`}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div>
            <Label>Modo de procesamiento</Label>
            <div className="mt-1 grid grid-cols-2 gap-2">
              {(
                [
                  { id: "CLOUD_API", icon: Cloud, title: "Cloud API", sub: "Claude / Gemini / OpenAI", ok: status?.cloud_available },
                  { id: "LOCAL_OLLAMA", icon: HardDrive, title: "Local Ollama", sub: "Confidencialidad estricta", ok: status?.ollama_available },
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
                  <span className="flex-1">
                    <span className="block text-sm font-medium">{opt.title}</span>
                    <span className="block text-xs text-muted-foreground">{opt.sub}</span>
                  </span>
                  {status && (
                    <span
                      className={cn("mt-1 h-2 w-2 rounded-full", opt.ok ? "bg-positive" : "bg-amber-500")}
                      title={opt.ok ? "Disponible" : "No disponible"}
                    />
                  )}
                </button>
              ))}
            </div>
            {modeNote && (
              <p className="mt-2 flex items-start gap-1.5 text-xs text-muted-foreground">
                <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {modeNote}
              </p>
            )}
          </div>

          <details className="text-sm">
            <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
              Datos de la empresa (opcional, si no hay certificado de Cámara)
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

          {error && (
            <p className="flex items-start gap-1.5 rounded-md bg-destructive/5 p-2 text-sm text-destructive">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
            </p>
          )}

          <Button onClick={upload} disabled={busy !== null || files.length === 0} className="w-full">
            {busy === "upload" ? <Loader2 className="animate-spin" /> : <Upload />}
            {busy === "upload" ? "Leyendo y validando archivos…" : `Generar expediente (${files.length} archivo${files.length === 1 ? "" : "s"})`}
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            El grafo de agentes corre en segundo plano y verá su progreso paso a paso.
          </p>
        </CardContent>
      </Card>
    </main>
  );
}

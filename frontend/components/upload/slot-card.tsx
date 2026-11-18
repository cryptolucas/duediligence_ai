"use client";

import { useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRightLeft,
  CheckCircle2,
  CircleDashed,
  FileSpreadsheet,
  FileText,
  Loader2,
  Upload,
  X,
  XCircle,
} from "lucide-react";
import type { DocumentValidation, UploadSlotId, UploadSlotSpec } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export interface FileEntry {
  id: string;
  file: File;
  slot: UploadSlotId;
  state: "validating" | "checked";
  validation: DocumentValidation | null;
}

export type SlotState = "empty" | "ready" | "validating" | "error";

export function entryStatus(entry: FileEntry): "validating" | DocumentValidation["status"] {
  return entry.state === "validating" || !entry.validation ? "validating" : entry.validation.status;
}

export function slotState(entries: FileEntry[]): SlotState {
  if (entries.some((e) => entryStatus(e) === "error")) return "error";
  if (entries.some((e) => entryStatus(e) === "validating")) return "validating";
  return entries.length ? "ready" : "empty";
}

const SPREADSHEET = [".xlsx", ".xls", ".xlsm", ".csv"];

function FileRow({
  entry,
  specsById,
  onRemove,
  onMove,
}: {
  entry: FileEntry;
  specsById: Record<string, UploadSlotSpec>;
  onRemove: () => void;
  onMove: (slot: UploadSlotId) => void;
}) {
  const status = entryStatus(entry);
  const v = entry.validation;
  const isSheet = SPREADSHEET.some((ext) => entry.file.name.toLowerCase().endsWith(ext));
  const suggested = v?.suggested_slot ? specsById[v.suggested_slot] : null;
  return (
    <li
      className={cn(
        "rounded-md border px-3 py-2 text-sm",
        status === "error" && "border-destructive/50 bg-destructive/5",
        status === "warning" && "border-amber-300 bg-amber-50/60",
      )}
    >
      <div className="flex items-center gap-2">
        {isSheet ? <FileSpreadsheet className="h-4 w-4 shrink-0 text-muted-foreground" /> : <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />}
        <span className="min-w-0 flex-1 truncate font-medium" title={entry.file.name}>
          {entry.file.name}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">{(entry.file.size / 1024 / 1024).toFixed(entry.file.size < 1024 * 1024 ? 2 : 1)} MB</span>
        <button onClick={onRemove} className="shrink-0 rounded p-1 hover:bg-muted" aria-label={`Quitar ${entry.file.name}`} title="Quitar">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="mt-1 flex items-start gap-1.5 text-xs">
        {status === "validating" && (
          <>
            <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-primary" />
            <span className="text-muted-foreground">Revisando el archivo…</span>
          </>
        )}
        {status === "valid" && (
          <>
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-positive" />
            <span>
              <span className="font-medium text-positive">Correcto.</span> {v?.summary}
            </span>
          </>
        )}
        {status === "warning" && (
          <>
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
            <span>
              <span className="font-medium text-amber-800">Se puede usar, con observaciones.</span> {v?.summary}
            </span>
          </>
        )}
        {status === "error" && (
          <>
            <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />
            <span className="font-medium text-destructive">No se puede usar este archivo.</span>
          </>
        )}
      </div>
      {v && v.issues.length > 0 && (
        <ul className="mt-1.5 space-y-1 pl-5 text-xs">
          {v.issues.map((issue, i) => (
            <li key={i} className="list-disc">
              <span className={issue.level === "error" ? "text-destructive" : "text-amber-900"}>{issue.message}</span>
              {issue.fix && <span className="block text-muted-foreground">Cómo solucionarlo: {issue.fix}</span>}
            </li>
          ))}
        </ul>
      )}
      {suggested && suggested.id !== entry.slot && (
        <Button variant="outline" size="sm" className="mt-2 h-7 text-xs" onClick={() => onMove(suggested.id)}>
          <ArrowRightLeft className="h-3.5 w-3.5" /> Mover a «{suggested.label}»
        </Button>
      )}
    </li>
  );
}

export function SlotCard({
  spec,
  entries,
  specsById,
  maxFileMb,
  onAdd,
  onRemove,
  onMove,
  disabled,
}: {
  spec: UploadSlotSpec;
  entries: FileEntry[];
  specsById: Record<string, UploadSlotSpec>;
  maxFileMb: number;
  onAdd: (files: File[]) => void;
  onRemove: (id: string) => void;
  onMove: (id: string, slot: UploadSlotId) => void;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const state = slotState(entries);
  const full = entries.length >= spec.max_files;
  const formats = spec.accepted_extensions.map((e) => e.slice(1).toUpperCase()).join(", ");

  const statusBadge = spec.required ? (
    state === "ready" ? (
      <Badge variant="positive">
        <CheckCircle2 className="h-3 w-3" /> Listo
      </Badge>
    ) : state === "error" ? (
      <Badge variant="critical">Revisar</Badge>
    ) : state === "validating" ? (
      <Badge variant="muted">
        <Loader2 className="h-3 w-3 animate-spin" /> Revisando
      </Badge>
    ) : (
      <Badge variant="high">Falta</Badge>
    )
  ) : null;

  return (
    <section
      className={cn(
        "rounded-lg border bg-card p-4 shadow-sm",
        spec.required && state === "ready" && "border-emerald-300",
        state === "error" && "border-destructive/50",
      )}
      aria-labelledby={`slot-${spec.id}`}
    >
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
            spec.required ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
          )}
        >
          {spec.required ? spec.number : "+"}
        </span>
        <h3 id={`slot-${spec.id}`} className="text-sm font-semibold">
          {spec.label}
        </h3>
        <Badge variant={spec.required ? "default" : "muted"}>{spec.required ? "Obligatorio" : "Opcional"}</Badge>
        {statusBadge}
      </header>

      <p className="text-sm">{spec.what_to_upload}</p>
      <div className="mt-2 grid gap-3 text-xs md:grid-cols-[3fr_2fr]">
        <div>
          <p className="mb-1 font-medium text-muted-foreground">{spec.required ? "Debe contener" : "Qué puede subir"}</p>
          <ul className="space-y-0.5">
            {spec.must_contain.map((item) => (
              <li key={item} className="flex gap-1.5">
                <CircleDashed className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" /> <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="space-y-1.5">
          <p>
            <span className="font-medium text-muted-foreground">Formatos:</span> {formats} · máx. {maxFileMb} MB por archivo
            {spec.max_files > 1 ? ` · hasta ${spec.max_files} archivos` : " · 1 archivo"}
          </p>
          <p>
            <span className="font-medium text-muted-foreground">Ejemplos:</span>{" "}
            {spec.examples.map((ex) => (
              <code key={ex} className="mr-1 inline-block rounded bg-muted px-1 py-0.5 text-[11px]">
                {ex}
              </code>
            ))}
          </p>
          <p className="text-muted-foreground">
            <span className="font-medium">Para qué sirve:</span> {spec.why_it_matters}
          </p>
        </div>
      </div>

      {entries.length > 0 && (
        <ul className="mt-3 space-y-2">
          {entries.map((entry) => (
            <FileRow
              key={entry.id}
              entry={entry}
              specsById={specsById}
              onRemove={() => onRemove(entry.id)}
              onMove={(slot) => onMove(entry.id, slot)}
            />
          ))}
        </ul>
      )}

      {!full && (
        <div
          role="button"
          tabIndex={disabled ? -1 : 0}
          aria-disabled={disabled}
          onClick={() => !disabled && inputRef.current?.click()}
          onKeyDown={(e) => !disabled && (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            if (!disabled) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            if (!disabled) onAdd(Array.from(e.dataTransfer.files));
          }}
          className={cn(
            "mt-3 flex cursor-pointer items-center justify-center gap-2 rounded-md border-2 border-dashed px-3 py-4 text-center text-sm transition-colors",
            dragging ? "border-primary bg-accent" : "border-input hover:bg-muted/60",
            disabled && "cursor-not-allowed opacity-60",
          )}
        >
          <Upload className="h-4 w-4 text-muted-foreground" />
          <span>
            <span className="font-medium">{entries.length ? "Agregar otro archivo" : "Arrastre el archivo aquí o haga clic para seleccionarlo"}</span>
            <span className="block text-xs text-muted-foreground">{formats}</span>
          </span>
          <input
            ref={inputRef}
            type="file"
            multiple={spec.max_files > 1}
            accept={spec.accepted_extensions.join(",")}
            className="hidden"
            onChange={(e) => {
              onAdd(Array.from(e.target.files ?? []));
              e.target.value = "";
            }}
          />
        </div>
      )}
    </section>
  );
}

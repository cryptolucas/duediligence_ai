"use client";

import { createContext, useContext } from "react";
import type { DisplayUnit } from "@/lib/format";
import type { DealView, RecalculateRequest, SourceCitation } from "@/lib/types";

export interface InspectorState {
  citations: SourceCitation[];
  index: number;
  title?: string;
}

export interface WorkspaceContextValue {
  view: DealView;
  citationIndex: Map<string, SourceCitation>;
  unit: DisplayUnit;
  trm: number;
  setUnit: (u: DisplayUnit) => void;
  setTrm: (t: number) => void;
  inspector: InspectorState | null;
  setInspector: (s: InspectorState | null) => void;
  /** Abre en el inspector una o varias citas (por id o por objeto). */
  openCitations: (refs: (string | SourceCitation)[], title?: string) => void;
  recalc: (body: RecalculateRequest) => Promise<boolean>;
  busy: boolean;
  lastRecalcMs: number | null;
  registerCitations: (citations: SourceCitation[]) => void;
}

export const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace debe usarse dentro de WorkspaceContext");
  return ctx;
}

"use client";

import { Info } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Markdown } from "./markdown";
import { useWorkspace } from "./workspace-context";

export function MemoTab() {
  const { view, unit } = useWorkspace();
  return (
    <div className="space-y-2">
      <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        Las cifras del memo las inyecta el motor determinista y se actualizan al cambiar ajustes. Haga clic en una cita para ver la fuente.
        {unit === "USD" && " El memo se presenta en COP."}
      </p>
      <Card className="p-5">
        <Markdown markdown={view.memo_markdown} />
      </Card>
    </div>
  );
}

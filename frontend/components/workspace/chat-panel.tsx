"use client";

import { useEffect, useRef, useState } from "react";
import { Bot, Loader2, MessageSquare, SendHorizontal, User } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { ChatHistoryEntry } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Markdown } from "./markdown";
import { useWorkspace } from "./workspace-context";

const SUGGESTIONS = [
  "¿Qué pasa con el EBITDA si excluimos el arriendo pagado al socio?",
  "¿De dónde sale el dato del litigio laboral?",
  "Dame un resumen del expediente",
];

export function ChatPanel() {
  const { view, registerCitations } = useWorkspace();
  const [messages, setMessages] = useState<ChatHistoryEntry[]>(view.chat_history);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || sending) return;
    setInput("");
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: message }]);
    setSending(true);
    try {
      const response = await api.chat(view.dossier.deal_id, message);
      registerCitations(response.citations);
      setMessages((prev) => [...prev, { role: "assistant", content: response.answer_markdown, mode: response.mode }]);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="flex items-center gap-1.5 text-sm font-semibold">
          <MessageSquare className="h-4 w-4 text-primary" /> Chat con el expediente
        </div>
        <span className="text-[11px] text-muted-foreground">Escenarios recalculados por el motor</span>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {messages.length === 0 && (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">Pregunte por fuentes, riesgos o simule escenarios de EBITDA:</p>
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => send(s)} className="block w-full rounded-md border px-2.5 py-1.5 text-left text-xs hover:bg-accent">
                {s}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={cn("flex gap-2", m.role === "user" && "flex-row-reverse")}>
            <div className={cn("mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full", m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted")}>
              {m.role === "user" ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
            </div>
            <div className={cn("min-w-0 max-w-[90%] rounded-lg px-3 py-2 text-sm", m.role === "user" ? "bg-primary text-primary-foreground" : "border bg-card")}>
              {m.role === "user" ? (
                <p className="whitespace-pre-wrap">{m.content}</p>
              ) : (
                <>
                  <Markdown markdown={m.content} className="[&_p]:text-[13px] [&_table]:text-xs" />
                  {m.mode && (
                    <Badge variant="muted" className="mt-1">
                      {m.mode === "LLM" ? "Respuesta LLM + motor" : "Respuesta determinista"}
                    </Badge>
                  )}
                </>
              )}
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Consultando el expediente…
          </div>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div ref={endRef} />
      </div>
      <form
        className="flex items-end gap-2 border-t p-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
          placeholder="Ej.: ¿qué pasa si rechazamos los honorarios legales?"
          className="min-h-[40px] resize-none text-sm"
          rows={1}
        />
        <Button type="submit" size="icon" className="h-10 w-10" disabled={sending || !input.trim()} aria-label="Enviar">
          <SendHorizontal />
        </Button>
      </form>
    </div>
  );
}

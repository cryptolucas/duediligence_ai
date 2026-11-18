"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { KeyRound, Loader2 } from "lucide-react";
import { api, ApiError, AUTH_REQUIRED_EVENT, getAccessCode, SERVER_WAKING_EVENT, setAccessCode } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";

/**
 * - Aviso cuando el servidor tarda en responder (en planes gratuitos "duerme" tras 15 min sin uso).
 * - Pantalla de código de acceso si el backend define ACCESS_CODE.
 */
export function AppGate({ children }: { children: React.ReactNode }) {
  const [waking, setWaking] = useState(false);
  const [needsCode, setNeedsCode] = useState(false);
  const [code, setCode] = useState("");
  const [checking, setChecking] = useState(false);
  const [codeError, setCodeError] = useState<string | null>(null);
  const pinging = useRef(false);

  const pingUntilAwake = useCallback(async () => {
    if (pinging.current) return;
    pinging.current = true;
    try {
      const health = await api.health();
      if (health.access_code_required && !getAccessCode()) setNeedsCode(true);
    } catch {
      /* el aviso de conexión lo muestra cada página */
    } finally {
      pinging.current = false;
      setWaking(false);
    }
  }, []);

  useEffect(() => {
    const slow = setTimeout(() => setWaking(true), 2500);
    pingUntilAwake().finally(() => clearTimeout(slow));
    const onWaking = () => {
      setWaking(true);
      pingUntilAwake();
    };
    const onAuth = () => {
      setAccessCode(null);
      setNeedsCode(true);
    };
    window.addEventListener(SERVER_WAKING_EVENT, onWaking);
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuth);
    return () => {
      clearTimeout(slow);
      window.removeEventListener(SERVER_WAKING_EVENT, onWaking);
      window.removeEventListener(AUTH_REQUIRED_EVENT, onAuth);
    };
  }, [pingUntilAwake]);

  async function submitCode(e: React.FormEvent) {
    e.preventDefault();
    if (!code.trim()) return;
    setChecking(true);
    setCodeError(null);
    setAccessCode(code.trim());
    try {
      await api.listDeals();
      window.location.reload();
    } catch (err) {
      setAccessCode(null);
      setCodeError((err as ApiError).status === 401 ? "El código no es correcto. Revíselo e intente de nuevo." : (err as ApiError).message);
      setNeedsCode(true);
      setChecking(false);
    }
  }

  return (
    <>
      {waking && (
        <div role="status" className="flex items-center justify-center gap-2 border-b bg-amber-50 px-4 py-2 text-xs text-amber-900">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Conectando con el servidor… Si estuvo inactivo, puede tardar hasta un minuto en despertar.
        </div>
      )}
      {children}
      {needsCode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <form onSubmit={submitCode} className="w-full max-w-sm space-y-3 rounded-lg border bg-background p-5 shadow-lg">
            <div className="flex items-center gap-2">
              <KeyRound className="h-5 w-5 text-primary" />
              <h2 className="text-base font-semibold">Código de acceso</h2>
            </div>
            <p className="text-sm text-muted-foreground">
              Esta es una versión de prueba privada. Escriba el código que recibió junto con el enlace.
            </p>
            <div>
              <Label htmlFor="access-code">Código</Label>
              <Input id="access-code" value={code} onChange={(e) => setCode(e.target.value)} autoFocus autoComplete="off" />
            </div>
            {codeError && <p className="text-sm text-destructive">{codeError}</p>}
            <Button type="submit" className="w-full" disabled={checking || !code.trim()}>
              {checking && <Loader2 className="animate-spin" />} Entrar
            </Button>
          </form>
        </div>
      )}
    </>
  );
}

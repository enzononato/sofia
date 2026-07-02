"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import axios from "axios";
import { useAuthStore } from "@/store/useAuthStore";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Bot, Loader2 } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

function AcceptInviteInner() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token") || "";
  const login = useAuthStore((s) => s.login);

  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!token) { setError("Convite inválido."); return; }
    if (password.length < 8) { setError("A senha deve ter no mínimo 8 caracteres."); return; }
    setIsSubmitting(true);
    try {
      const { data } = await axios.post(`${API_URL}/auth/accept-invite`, {
        token,
        full_name: fullName,
        password,
      });
      await login(data.access_token, data.refresh_token);
      router.push("/dashboard");
    } catch (err: unknown) {
      const anyErr = err as { response?: { data?: { error?: { message?: string }; detail?: string } } };
      setError(anyErr?.response?.data?.error?.message || anyErr?.response?.data?.detail || "Não foi possível aceitar o convite. Ele pode ter expirado.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4 relative overflow-hidden">
      {/* Background glow elements */}
      <div className="absolute top-1/4 left-1/4 -translate-x-1/2 -translate-y-1/2 w-80 h-80 rounded-full bg-primary/10 blur-[120px] pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 translate-x-1/2 translate-y-1/2 w-80 h-80 rounded-full bg-indigo-500/10 blur-[120px] pointer-events-none" />

      <div className="w-full max-w-md bg-white/[0.03] backdrop-blur-xl border border-white/10 p-8 rounded-[28px] shadow-2xl relative z-10 animate-in fade-in slide-in-from-bottom-4 duration-300">
        <div className="flex flex-col items-center mb-6">
          <div className="w-14 h-14 bg-gradient-to-tr from-violet-600 to-indigo-600 text-white rounded-2xl flex items-center justify-center shadow-lg shadow-primary/20 mb-4 ring-1 ring-white/10">
            <Bot size={28} />
          </div>
          <h1 className="font-heading text-2xl font-bold tracking-tight text-foreground text-center">Ativar seu acesso</h1>
          <p className="text-xs text-muted-foreground/80 mt-1.5 text-center font-sans max-w-[280px]">
            Defina seu nome e senha para entrar na equipe da clínica.
          </p>
        </div>

        {!token ? (
          <p className="text-xs text-destructive text-center font-sans font-medium">Link de convite inválido ou incompleto.</p>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="full_name" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Nome completo</Label>
              <Input id="full_name" value={fullName} onChange={(e) => setFullName(e.target.value)} required placeholder="Seu nome" className="h-11 rounded-xl border border-white/10 bg-background/55 text-foreground px-4 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 focus:border-primary/50 transition-all w-full" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Senha (mín. 8 caracteres)</Label>
              <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required className="h-11 rounded-xl border border-white/10 bg-background/55 text-foreground px-4 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 focus:border-primary/50 transition-all w-full" />
            </div>
            {error && <p className="text-xs text-destructive font-sans font-medium text-center">{error}</p>}
            <button type="submit" disabled={isSubmitting} className="sofia-btn-gradient w-full h-11 rounded-xl text-white font-bold text-xs shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center disabled:opacity-50 mt-2">
              {isSubmitting && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
              Ativar acesso
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center bg-background"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>}>
      <AcceptInviteInner />
    </Suspense>
  );
}

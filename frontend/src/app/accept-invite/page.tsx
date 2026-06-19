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
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm rounded-2xl border border-border/50 bg-card p-8 shadow-lg">
        <div className="flex flex-col items-center mb-6">
          <div className="w-12 h-12 bg-primary/10 text-primary rounded-xl flex items-center justify-center ring-1 ring-primary/20 mb-3">
            <Bot size={24} />
          </div>
          <h1 className="text-xl font-bold tracking-tight">Ativar seu acesso</h1>
          <p className="text-sm text-muted-foreground mt-1 text-center">
            Defina seu nome e senha para entrar na equipe.
          </p>
        </div>

        {!token ? (
          <p className="text-sm text-destructive text-center">Link de convite inválido ou incompleto.</p>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="full_name">Nome completo</Label>
              <Input id="full_name" value={fullName} onChange={(e) => setFullName(e.target.value)} required placeholder="Seu nome" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Senha (mín. 8 caracteres)</Label>
              <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Ativar acesso
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>}>
      <AcceptInviteInner />
    </Suspense>
  );
}

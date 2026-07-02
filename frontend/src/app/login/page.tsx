"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { motion } from "framer-motion";
import {
  Sparkles,
  Loader2,
  Lock,
  Mail,
  Eye,
  EyeOff,
  ArrowRight,
  AlertCircle,
} from "lucide-react";
import api from "@/lib/axios";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { useAuthStore } from "@/store/useAuthStore";
import Link from "next/link";

const loginSchema = z.object({
  email: z.string().email({ message: "Insira um e-mail válido" }),
  password: z.string().min(6, { message: "A senha deve ter no mínimo 6 caracteres" }),
});const inputClass =
  "h-12 rounded-xl border border-white/10 bg-background/55 text-foreground pl-11 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus-visible:border-primary/50 transition-all w-full placeholder:text-muted-foreground/60";

export default function LoginPage() {
  const router = useRouter();
  const login = useAuthStore((state) => state.login);
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const form = useForm<z.infer<typeof loginSchema>>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      email: "",
      password: "",
    },
  });

  async function onSubmit(values: z.infer<typeof loginSchema>) {
    try {
      setError(null);

      const response = await api.post("/auth/login", {
        email: values.email,
        password: values.password,
      });

      const { access_token, refresh_token } = response.data;
      await login(access_token, refresh_token);

      router.push("/dashboard/inbox");
    } catch (err: any) {
      console.error(err);

      const backendError = err.response?.data?.error?.message;

      if (backendError) {
        setError(backendError);
      } else if (err.response?.status === 401 || err.response?.status === 403) {
        setError("Credenciais inválidas. Verifique seu e-mail e senha.");
      } else {
        setError("Ocorreu um erro ao fazer login. Tente novamente mais tarde.");
      }
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-4 md:p-8 bg-background">
      {/* Ambient aurora backdrop */}
      <div className="aurora-bg" aria-hidden="true">
        <div className="aurora-blob aurora-violet" />
        <div className="aurora-blob aurora-cyan" />
      </div>

      <main className="grid w-full max-w-5xl items-center gap-10 lg:grid-cols-2 relative z-10">
        {/* Left: brand / storytelling (desktop only) */}
        <section className="hidden flex-col items-start gap-6 lg:flex">
          <div className="flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-tr from-violet-600 to-indigo-600 shadow-lg shadow-primary/20 ring-1 ring-white/10">
              <Sparkles className="h-5 w-5 text-white" />
            </div>
            <span className="font-heading text-2xl font-extrabold tracking-tight text-white">
              Sofia AI
            </span>
          </div>

          <div className="mt-6">
            <h1 className="font-heading text-4xl font-bold leading-tight text-white md:text-5xl">
              Desperte a{" "}
              <span className="bg-gradient-to-r from-primary to-[#fbabff] bg-clip-text text-transparent animate-pulse">
                Sofia
              </span>
            </h1>
            <p className="mt-4 max-w-sm text-sm text-muted-foreground/80 font-sans leading-relaxed">
              A inteligência artificial que transforma seu atendimento no WhatsApp
              em uma experiência de saúde de elite.
            </p>
          </div>

          <div className="glass-card mt-6 flex items-center gap-4 rounded-2xl p-6 border border-white/10 bg-white/5">
            <div className="flex h-11 w-11 items-center justify-center rounded-full bg-primary/15 ring-1 ring-primary/25">
              <Sparkles className="h-5 w-5 text-primary" />
            </div>
            <div>
              <p className="font-mono text-[10px] uppercase tracking-wider text-primary font-bold">
                Sofia Assistant
              </p>
              <p className="text-xs text-white/90 font-sans mt-0.5">
                Atendimento humano, 24 horas por dia.
              </p>
            </div>
          </div>
        </section>

        {/* Right: login form */}
        <section className="flex justify-center lg:justify-end">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
            className="glass-card relative w-full max-w-[420px] overflow-hidden rounded-[28px] p-8 md:p-10 border border-white/10 bg-white/[0.03] backdrop-blur-xl shadow-2xl"
          >
            {/* corner glow */}
            <div className="pointer-events-none absolute -right-12 -top-12 h-32 w-32 rounded-full bg-primary/20 blur-3xl" />

            <div className="relative z-10 flex flex-col gap-6">
              <header className="flex flex-col gap-1.5">
                {/* mobile brand */}
                <div className="mb-2 flex items-center gap-2 lg:hidden">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-tr from-violet-600 to-indigo-600 text-white">
                    <Sparkles className="h-4.5 w-4.5 text-white" />
                  </div>
                  <span className="font-heading text-xl font-bold text-white">
                    Sofia AI
                  </span>
                </div>
                <h2 className="font-heading text-2xl font-bold text-white">
                  Bem-vindo de volta
                </h2>
                <p className="text-xs text-muted-foreground/80 font-sans">
                  Insira suas credenciais para acessar o painel inteligente.
                </p>
              </header>

              <Form {...form}>
                <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4">
                  <FormField
                    control={form.control}
                    name="email"
                    render={({ field }) => (
                      <FormItem className="space-y-1.5">
                        <FormLabel className="ml-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">
                          E-mail profissional
                        </FormLabel>
                        <FormControl>
                          <div className="relative">
                            <Mail className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/60" />
                            <Input
                              type="email"
                              placeholder="seu@clinica.com"
                              className={inputClass}
                              {...field}
                            />
                          </div>
                        </FormControl>
                        <FormMessage className="text-xs text-destructive font-sans font-medium" />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="password"
                    render={({ field }) => (
                      <FormItem className="space-y-1.5">
                        <div className="flex items-center justify-between px-1">
                          <FormLabel className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">
                            Sua senha
                          </FormLabel>
                          <Link
                            href="#"
                            className="text-xs font-semibold text-primary hover:underline font-sans"
                          >
                            Esqueceu?
                          </Link>
                        </div>
                        <FormControl>
                          <div className="relative">
                            <Lock className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/60" />
                            <Input
                              type={showPassword ? "text" : "password"}
                              placeholder="••••••••"
                              className={`${inputClass} pr-11`}
                              {...field}
                            />
                            <button
                              type="button"
                              onClick={() => setShowPassword((v) => !v)}
                              className="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground/60 transition-colors hover:text-white cursor-pointer"
                              aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"}
                            >
                              {showPassword ? (
                                <EyeOff className="h-4 w-4" />
                              ) : (
                                <Eye className="h-4 w-4" />
                              )}
                            </button>
                          </div>
                        </FormControl>
                        <FormMessage className="text-xs text-destructive font-sans font-medium" />
                      </FormItem>
                    )}
                  />

                  {error && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      className="flex items-center gap-2 rounded-xl border border-destructive/20 bg-destructive/5 p-3"
                    >
                      <AlertCircle className="h-4 w-4 shrink-0 text-destructive" />
                      <p className="text-xs text-destructive font-sans font-medium">{error}</p>
                    </motion.div>
                  )}

                  <button
                    type="submit"
                    className="sofia-btn-gradient group mt-2 h-12 w-full rounded-xl text-xs font-bold text-white shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center disabled:opacity-50"
                    disabled={form.formState.isSubmitting}
                  >
                    {form.formState.isSubmitting ? (
                      <>
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                        Entrando...
                      </>
                    ) : (
                      <>
                        Entrar
                        <ArrowRight className="ml-1 h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
                      </>
                    )}
                  </button>
                </form>
              </Form>

              <p className="text-center text-xs text-muted-foreground font-sans">
                Não tem uma conta?{" "}
                <Link
                  href="/signup"
                  className="font-bold text-primary transition-colors hover:underline"
                >
                  Criar conta
                </Link>
              </p>
            </div>
          </motion.div>
        </section>
      </main>
    </div>
  );
}

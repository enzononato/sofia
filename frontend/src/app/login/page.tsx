"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { motion } from "framer-motion";
import { Bot, Loader2, Lock, Mail } from "lucide-react";
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
});

export default function LoginPage() {
  const router = useRouter();
  const login = useAuthStore((state) => state.login);
  const [error, setError] = useState<string | null>(null);
  
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

      // Handle successful login
      const { access_token, refresh_token } = response.data;
      await login(access_token, refresh_token);
      
      router.push("/dashboard/inbox");
    } catch (err: any) {
      console.error(err);
      
      // Extract structured error from backend if available
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
    <div className="min-h-screen bg-gradient-premium flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="w-full max-w-md"
      >
        <div className="glass rounded-2xl p-8 space-y-8">
          <div className="text-center space-y-2">
            <div className="mx-auto w-12 h-12 bg-[color-mix(in_oklch,var(--primary)_20%,transparent)] text-primary rounded-xl flex items-center justify-center mb-6 ring-1 ring-[color-mix(in_oklch,var(--primary)_30%,transparent)]">
              <Bot size={28} />
            </div>
            <h1 className="text-3xl font-bold tracking-tight">Bem-vindo à Sofia</h1>
            <p className="text-muted-foreground text-sm">
              Sua clínica no piloto automático.
            </p>
          </div>

          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>E-mail</FormLabel>
                    <FormControl>
                      <div className="relative">
                        <Mail className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                        <Input
                          placeholder="clinica@exemplo.com"
                          className="pl-10 bg-[color-mix(in_oklch,var(--background)_50%,transparent)] focus:bg-background transition-colors"
                          {...field}
                        />
                      </div>
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <div className="flex items-center justify-between">
                      <FormLabel>Senha</FormLabel>
                      <Link href="#" className="text-xs text-primary hover:underline">
                        Esqueceu a senha?
                      </Link>
                    </div>
                    <FormControl>
                      <div className="relative">
                        <Lock className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                        <Input
                          type="password"
                          placeholder="••••••••"
                          className="pl-10 bg-[color-mix(in_oklch,var(--background)_50%,transparent)] focus:bg-background transition-colors"
                          {...field}
                        />
                      </div>
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {error && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  className="text-destructive text-sm font-medium text-center bg-[color-mix(in_oklch,var(--destructive)_10%,transparent)] py-2 rounded-md"
                >
                  {error}
                </motion.div>
              )}

              <Button
                type="submit"
                className="w-full h-11 text-base font-medium shadow-lg shadow-[color-mix(in_oklch,var(--primary)_20%,transparent)]"
                disabled={form.formState.isSubmitting}
              >
                {form.formState.isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Entrando...
                  </>
                ) : (
                  "Entrar"
                )}
              </Button>
            </form>
          </Form>

          <div className="text-center text-sm text-muted-foreground">
            Ainda não tem uma conta?{" "}
            <Link
              href="/signup"
              className="text-primary font-medium hover:underline transition-colors"
            >
              Crie sua clínica
            </Link>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

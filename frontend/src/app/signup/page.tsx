"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { motion } from "framer-motion";
import { Bot, Loader2, Lock, Mail, Building, User } from "lucide-react";
import axios from "axios";

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

const signupSchema = z.object({
  clinic_name: z.string().min(2, { message: "Nome da clínica deve ter no mínimo 2 caracteres" }),
  clinic_slug: z.string().min(2, { message: "Slug inválido" }).regex(/^[a-z0-9-]+$/, "Apenas letras minúsculas, números e hifens"),
  clinic_email: z.string().email({ message: "E-mail da clínica inválido" }),
  owner_name: z.string().min(2, { message: "Seu nome é obrigatório" }),
  owner_email: z.string().email({ message: "Seu e-mail pessoal é obrigatório" }),
  password: z.string().min(6, { message: "A senha deve ter no mínimo 6 caracteres" }),
});

export default function SignupPage() {
  const router = useRouter();
  const login = useAuthStore((state) => state.login);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState(1);
  
  const form = useForm<z.infer<typeof signupSchema>>({
    resolver: zodResolver(signupSchema),
    defaultValues: {
      clinic_name: "",
      clinic_slug: "",
      clinic_email: "",
      owner_name: "",
      owner_email: "",
      password: "",
    },
  });

  // Auto-generate slug from clinic name
  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const name = e.target.value;
    form.setValue("clinic_name", name);
    if (!form.formState.touchedFields.clinic_slug) {
      const slug = name
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/(^-|-$)+/g, "");
      form.setValue("clinic_slug", slug);
    }
  };

  const validateStepOne = async () => {
    const isValid = await form.trigger(["clinic_name", "clinic_slug", "clinic_email"]);
    if (isValid) setStep(2);
  };

  async function onSubmit(values: z.infer<typeof signupSchema>) {
    try {
      setError(null);
      
      const response = await axios.post(
        `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/auth/signup`,
        values
      );

      // Handle successful signup
      const { access_token, refresh_token } = response.data;
      await login(access_token, refresh_token);
      
      router.push("/dashboard/inbox");
    } catch (err: any) {
      console.error(err);
      
      const backendError = err.response?.data?.error?.message;
      
      if (backendError) {
        setError(backendError);
      } else if (err.response?.status === 409) {
        setError("Esse slug de clínica ou e-mail já está em uso.");
      } else {
        setError("Ocorreu um erro ao criar a conta. Tente novamente.");
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
            <h1 className="text-3xl font-bold tracking-tight">Crie sua clínica</h1>
            <p className="text-muted-foreground text-sm">
              Automatize seu atendimento em minutos.
            </p>
          </div>

          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
              
              {/* Passo 1: Dados da Clínica */}
              {step === 1 && (
                <motion.div
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 20 }}
                  className="space-y-4"
                >
                  <FormField
                    control={form.control}
                    name="clinic_name"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Nome da Clínica</FormLabel>
                        <FormControl>
                          <div className="relative">
                            <Building className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                            <Input
                              placeholder="Ex: Clínica Sorriso"
                              className="pl-10 bg-[color-mix(in_oklch,var(--background)_50%,transparent)] focus:bg-background transition-colors"
                              {...field}
                              onChange={handleNameChange}
                            />
                          </div>
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  
                  <FormField
                    control={form.control}
                    name="clinic_slug"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Identificador único (URL)</FormLabel>
                        <FormControl>
                          <div className="flex items-center">
                            <span className="bg-muted px-3 py-2 text-sm text-muted-foreground border border-r-0 border-input rounded-l-md">
                              app.sofia.com/
                            </span>
                            <Input
                              placeholder="clinica-sorriso"
                              className="rounded-l-none bg-[color-mix(in_oklch,var(--background)_50%,transparent)] focus:bg-background transition-colors"
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
                    name="clinic_email"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>E-mail de Contato da Clínica</FormLabel>
                        <FormControl>
                          <div className="relative">
                            <Mail className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                            <Input
                              placeholder="contato@clinica.com"
                              className="pl-10 bg-[color-mix(in_oklch,var(--background)_50%,transparent)] focus:bg-background transition-colors"
                              {...field}
                            />
                          </div>
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <Button
                    type="button"
                    onClick={validateStepOne}
                    className="w-full h-11 text-base font-medium shadow-lg shadow-[color-mix(in_oklch,var(--primary)_20%,transparent)] mt-6"
                  >
                    Continuar
                  </Button>
                </motion.div>
              )}

              {/* Passo 2: Dados do Dono */}
              {step === 2 && (
                <motion.div
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="space-y-4"
                >
                  <FormField
                    control={form.control}
                    name="owner_name"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Seu Nome</FormLabel>
                        <FormControl>
                          <div className="relative">
                            <User className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                            <Input
                              placeholder="Dr. João Silva"
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
                    name="owner_email"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Seu E-mail Pessoal</FormLabel>
                        <FormControl>
                          <div className="relative">
                            <Mail className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                            <Input
                              placeholder="joao@gmail.com"
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
                        <FormLabel>Sua Senha</FormLabel>
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

                  <div className="flex gap-3 pt-2">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setStep(1)}
                      className="w-1/3 h-11"
                    >
                      Voltar
                    </Button>
                    <Button
                      type="submit"
                      className="w-2/3 h-11 text-base font-medium shadow-lg shadow-[color-mix(in_oklch,var(--primary)_20%,transparent)]"
                      disabled={form.formState.isSubmitting}
                    >
                      {form.formState.isSubmitting ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Criando...
                        </>
                      ) : (
                        "Criar Conta"
                      )}
                    </Button>
                  </div>
                </motion.div>
              )}

            </form>
          </Form>

          <div className="text-center text-sm text-muted-foreground">
            Já tem uma conta?{" "}
            <Link
              href="/login"
              className="text-primary font-medium hover:underline transition-colors"
            >
              Fazer login
            </Link>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

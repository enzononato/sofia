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
  Building,
  User,
  Eye,
  EyeOff,
  ArrowRight,
  ArrowLeft,
  Rocket,
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

const signupSchema = z.object({
  clinic_name: z.string().min(2, { message: "Nome da clínica deve ter no mínimo 2 caracteres" }),
  clinic_slug: z
    .string()
    .min(2, { message: "Slug inválido" })
    .regex(/^[a-z0-9-]+$/, "Apenas letras minúsculas, números e hifens"),
  clinic_email: z.string().email({ message: "E-mail da clínica inválido" }),
  owner_name: z.string().min(2, { message: "Seu nome é obrigatório" }),
  owner_email: z.string().email({ message: "Seu e-mail pessoal é obrigatório" }),
  password: z.string().min(6, { message: "A senha deve ter no mínimo 6 caracteres" }),
});

const inputClass =
  "h-12 rounded-xl border border-white/10 bg-background/55 text-foreground pl-11 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus-visible:border-primary/50 transition-all w-full placeholder:text-muted-foreground/60";

const labelClass =
  "ml-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block mb-1";

export default function SignupPage() {
  const router = useRouter();
  const login = useAuthStore((state) => state.login);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState(1);
  const [showPassword, setShowPassword] = useState(false);

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
        .replace(/[̀-ͯ]/g, "")
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

      const response = await api.post("/auth/signup", values);

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
              O futuro da sua clínica{" "}
              <span className="bg-gradient-to-r from-primary to-[#fbabff] bg-clip-text text-transparent animate-pulse">
                começa aqui.
              </span>
            </h1>
            <p className="mt-4 max-w-sm text-sm text-muted-foreground/80 font-sans leading-relaxed">
              Automatize sua gestão com a inteligência empática da Sofia. Em poucos
              minutos, sua clínica estará pronta para o próximo nível.
            </p>
          </div>

          <div className="glass-card mt-6 flex items-start gap-4 rounded-2xl p-6 border border-white/10 bg-white/5">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary/15 ring-1 ring-primary/25">
              <Sparkles className="h-5 w-5 text-primary" />
            </div>
            <div>
              <p className="font-mono text-[10px] uppercase tracking-wider text-primary font-bold">
                Experiência IA-first
              </p>
              <p className="mt-1.5 text-xs text-white/90 font-sans leading-relaxed">
                &quot;Olá! Sou a Sofia. Vou te guiar na configuração do seu novo
                ecossistema digital.&quot;
              </p>
            </div>
          </div>
        </section>

        {/* Right: signup form */}
        <section className="flex justify-center lg:justify-end">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
            className="glass-card relative w-full max-w-[460px] overflow-hidden rounded-[28px] p-8 md:p-10 border border-white/10 bg-white/[0.03] backdrop-blur-xl shadow-2xl"
          >
            <div className="pointer-events-none absolute -right-12 -top-12 h-32 w-32 rounded-full bg-primary/20 blur-3xl" />

            <div className="relative z-10 flex flex-col gap-6">
              {/* mobile brand */}
              <div className="flex items-center gap-2 lg:hidden">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-tr from-violet-600 to-indigo-600 text-white">
                  <Sparkles className="h-4.5 w-4.5 text-white" />
                </div>
                <span className="font-heading text-xl font-bold text-white">Sofia AI</span>
              </div>

              {/* progress indicator */}
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <span className="font-mono text-[10px] uppercase tracking-widest text-primary font-bold">
                    Passo {step} de 2
                  </span>
                  <span className="font-heading text-sm font-semibold text-white">
                    {step === 1 ? "Dados da Clínica" : "Sua Conta"}
                  </span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full bg-primary shadow-[0_0_10px_rgba(208,188,255,0.5)] transition-all duration-500 ease-out"
                    style={{ width: step === 1 ? "50%" : "100%" }}
                  />
                </div>
              </div>

              <Form {...form}>
                <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4">
                  {/* Step 1 — clinic data */}
                  {step === 1 && (
                    <motion.div
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      className="flex flex-col gap-4 animate-in fade-in slide-in-from-left-4 duration-300"
                    >
                      <FormField
                        control={form.control}
                        name="clinic_name"
                        render={({ field }) => (
                          <FormItem className="space-y-1.5">
                            <FormLabel className={labelClass}>Nome da clínica</FormLabel>
                            <FormControl>
                              <div className="relative">
                                <Building className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/60" />
                                <Input
                                  placeholder="Ex: Clínica Bem Estar"
                                  className={inputClass}
                                  {...field}
                                  onChange={handleNameChange}
                                />
                              </div>
                            </FormControl>
                            <FormMessage className="text-xs text-destructive font-sans font-medium" />
                          </FormItem>
                        )}
                      />

                      <FormField
                        control={form.control}
                        name="clinic_slug"
                        render={({ field }) => (
                          <FormItem className="space-y-1.5">
                            <FormLabel className={labelClass}>Identificador (URL)</FormLabel>
                            <FormControl>
                              <div className="flex items-center overflow-hidden rounded-xl border border-white/10 bg-background/55 focus-within:border-primary focus-within:ring-1 focus-within:ring-primary/50 transition-all">
                                <span className="select-none pl-4 pr-1 text-sm text-muted-foreground/60 font-mono">
                                  app.sofia.com/
                                </span>
                                <Input
                                  placeholder="minha-clinica"
                                  className="h-12 flex-1 rounded-none border-0 bg-transparent pl-1 text-sm focus-visible:ring-0 dark:bg-transparent"
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
                        name="clinic_email"
                        render={({ field }) => (
                          <FormItem className="space-y-1.5">
                            <FormLabel className={labelClass}>E-mail da clínica</FormLabel>
                            <FormControl>
                              <div className="relative">
                                <Mail className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/60" />
                                <Input
                                  type="email"
                                  placeholder="contato@clinica.com"
                                  className={inputClass}
                                  {...field}
                                />
                              </div>
                            </FormControl>
                            <FormMessage className="text-xs text-destructive font-sans font-medium" />
                          </FormItem>
                        )}
                      />

                      <button
                        type="button"
                        onClick={validateStepOne}
                        className="sofia-btn-gradient group mt-2 h-12 w-full rounded-xl text-xs font-bold text-white shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center"
                      >
                        Continuar
                        <ArrowRight className="ml-1 h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
                      </button>
                    </motion.div>
                  )}

                  {/* Step 2 — owner account */}
                  {step === 2 && (
                    <motion.div
                      initial={{ opacity: 0, x: 20 }}
                      animate={{ opacity: 1, x: 0 }}
                      className="flex flex-col gap-4 animate-in fade-in slide-in-from-right-4 duration-300"
                    >
                      <FormField
                        control={form.control}
                        name="owner_name"
                        render={({ field }) => (
                          <FormItem className="space-y-1.5">
                            <FormLabel className={labelClass}>Seu nome completo</FormLabel>
                            <FormControl>
                              <div className="relative">
                                <User className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/60" />
                                <Input
                                  placeholder="Dr. João Silva"
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
                        name="owner_email"
                        render={({ field }) => (
                          <FormItem className="space-y-1.5">
                            <FormLabel className={labelClass}>Seu e-mail pessoal</FormLabel>
                            <FormControl>
                              <div className="relative">
                                <Mail className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/60" />
                                <Input
                                  type="email"
                                  placeholder="joao@gmail.com"
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
                            <FormLabel className={labelClass}>Senha</FormLabel>
                            <FormControl>
                              <div className="relative">
                                <Lock className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/60" />
                                <Input
                                  type={showPassword ? "text" : "password"}
                                  placeholder="Mínimo 6 caracteres"
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

                      <div className="mt-2 flex gap-3">
                        <button
                          type="button"
                          onClick={() => setStep(1)}
                          className="h-12 flex-1 rounded-xl border border-white/10 bg-white/5 text-muted-foreground hover:text-foreground hover:bg-white/10 transition-all cursor-pointer font-semibold text-xs flex items-center justify-center gap-1.5"
                        >
                          <ArrowLeft className="mr-1 h-3.5 w-3.5" />
                          Voltar
                        </button>
                        <button
                          type="submit"
                          className="sofia-btn-gradient group h-12 flex-[2] rounded-xl text-xs font-bold text-white shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center disabled:opacity-50"
                          disabled={form.formState.isSubmitting}
                        >
                          {form.formState.isSubmitting ? (
                            <>
                              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                              Criando...
                            </>
                          ) : (
                            <>
                              Criar conta
                              <Rocket className="ml-1 h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
                            </>
                          )}
                        </button>
                      </div>
                    </motion.div>
                  )}
                </form>
              </Form>

              <p className="text-center text-xs text-muted-foreground font-sans">
                Já tem uma conta?{" "}
                <Link
                  href="/login"
                  className="font-bold text-primary transition-colors hover:underline"
                >
                  Entre aqui
                </Link>
              </p>
            </div>
          </motion.div>
        </section>
      </main>
    </div>
  );
}

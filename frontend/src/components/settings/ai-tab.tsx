"use client";

import { useState } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { TenantProfile, useUpdateTenant } from "@/hooks/useSettings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Bot, MessageSquare, SlidersHorizontal, Save, Loader2, Sparkles, Users, Layers, AlertTriangle, CalendarClock } from "lucide-react";
import { cn } from "@/lib/utils";

// Sofia's personality/behavior (base prompt + per-stage overlays) is fixed in
// code — not tenant-configurable. Clinics provide clinic INFO (Configurações →
// Informações Públicas / Horários), never instructions that change how Sofia
// acts. This form only manages technical AI parameters + toggles.
const formSchema = z.object({
  model: z.string().min(1, "Obrigatório"),
  temperature: z.coerce.number().min(0).max(2).optional(),
  max_output_tokens: z.coerce.number().min(100).optional(),
  multimodal_enabled: z.boolean().default(true),
  multi_agent_enabled: z.boolean().default(false),
});

type FormValues = z.infer<typeof formSchema>;

export function AiTab({ tenant }: { tenant: TenantProfile }) {
  const { mutateAsync: updateTenant, isPending } = useUpdateTenant();
  const [isSuccess, setIsSuccess] = useState(false);

  // ── Scheduling mode (capacity × per-professional) ──────────────────────────
  // Self-contained: saves on select via the deep-merge PATCH, independent of the
  // main AI form below, so it never clobbers the other ai_config keys.
  // Per-professional is the default: only an explicit "capacity" shows capacity.
  const [schedulingMode, setSchedulingMode] = useState<"capacity" | "per_professional">(
    tenant.ai_config?.scheduling_mode === "capacity" ? "capacity" : "per_professional"
  );
  const [modeSaving, setModeSaving] = useState(false);
  const [modeSaved, setModeSaved] = useState(false);

  const handleSelectMode = async (mode: "capacity" | "per_professional") => {
    if (mode === schedulingMode || modeSaving) return;
    const previous = schedulingMode;
    setSchedulingMode(mode);
    setModeSaving(true);
    setModeSaved(false);
    try {
      await updateTenant({ ai_config: { scheduling_mode: mode } });
      setModeSaved(true);
      setTimeout(() => setModeSaved(false), 3000);
    } catch (error) {
      console.error("Failed to update scheduling mode", error);
      setSchedulingMode(previous); // revert optimistic change on failure
    } finally {
      setModeSaving(false);
    }
  };

  const defaultValues = tenant.ai_config || {
    model: "gemini-2.5-flash",
    temperature: 0.7,
    max_output_tokens: 1024,
  };

  const { register, handleSubmit, control, formState: { errors } } = useForm<z.infer<typeof formSchema>>({
    resolver: zodResolver(formSchema) as any,
    defaultValues: {
      model: defaultValues.model || "gemini-2.5-flash",
      temperature: defaultValues.temperature || 0.7,
      max_output_tokens: defaultValues.max_output_tokens || 1024,
      // Multimodal defaults ON (only an explicit false disables it).
      multimodal_enabled: defaultValues.multimodal_enabled ?? true,
      // Multi-agent defaults OFF (opt-in per clinic; see AI_MULTI_AGENT_ENABLED).
      multi_agent_enabled: defaultValues.multi_agent_enabled ?? false,
    },
  });

  const onSubmit = async (data: FormValues) => {
    try {
      setIsSuccess(false);
      // Send explicit values so the backend top-level merge overwrites these
      // keys instead of keeping stale ones. Unmanaged keys like
      // `scheduling_mode` are preserved by the merge.
      await updateTenant({
        ai_config: {
          model: data.model,
          temperature: data.temperature,
          max_output_tokens: data.max_output_tokens,
          multimodal_enabled: data.multimodal_enabled,
          multi_agent_enabled: data.multi_agent_enabled,
        }
      });
      setIsSuccess(true);
      setTimeout(() => setIsSuccess(false), 3000);
    } catch (error) {
      console.error("Failed to update AI settings", error);
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-6 max-w-3xl bg-background/5">
      <div>
        <h3 className="font-heading text-lg font-bold text-foreground">Inteligência Artificial (Sofia)</h3>
        <p className="text-xs text-muted-foreground/80 font-sans mt-0.5">
          Ajustes técnicos do modelo de IA e do comportamento de atendimento da Sofia.
        </p>
      </div>

      {/* ── Scheduling mode ── */}
      <div className="rounded-2xl border border-white/10 bg-white/5 p-5 shadow-md space-y-4">
        <div>
          <Label className="font-heading text-sm font-semibold text-foreground flex items-center gap-2">
            <CalendarClock className="h-4 w-4 text-primary" />
            Modo de agendamento
          </Label>
          <p className="text-xs text-muted-foreground/80 font-sans mt-0.5 leading-relaxed">
            Define como a Sofia verifica disponibilidade e agenda os pacientes.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <button
            type="button"
            onClick={() => handleSelectMode("capacity")}
            disabled={modeSaving}
            className={cn(
              "text-left rounded-xl border p-4 transition-all cursor-pointer disabled:cursor-not-allowed",
              schedulingMode === "capacity"
                ? "border-primary/50 bg-primary/10 ring-1 ring-primary/30"
                : "border-white/10 bg-background/40 hover:bg-white/5"
            )}
          >
            <div className="flex items-center gap-2 mb-1">
              <Layers className={cn("h-4 w-4", schedulingMode === "capacity" ? "text-primary" : "text-muted-foreground/70")} />
              <span className="font-heading text-sm font-semibold text-foreground">Por capacidade</span>
            </div>
            <p className="text-xs text-muted-foreground/80 font-sans leading-relaxed">
              A clínica atende N pacientes ao mesmo tempo. A Sofia não atribui um profissional específico ao agendar.
            </p>
          </button>

          <button
            type="button"
            onClick={() => handleSelectMode("per_professional")}
            disabled={modeSaving}
            className={cn(
              "text-left rounded-xl border p-4 transition-all cursor-pointer disabled:cursor-not-allowed",
              schedulingMode === "per_professional"
                ? "border-primary/50 bg-primary/10 ring-1 ring-primary/30"
                : "border-white/10 bg-background/40 hover:bg-white/5"
            )}
          >
            <div className="flex items-center gap-2 mb-1">
              <Users className={cn("h-4 w-4", schedulingMode === "per_professional" ? "text-primary" : "text-muted-foreground/70")} />
              <span className="font-heading text-sm font-semibold text-foreground">Por profissional</span>
            </div>
            <p className="text-xs text-muted-foreground/80 font-sans leading-relaxed">
              Cada agendamento é atribuído a um profissional, respeitando os serviços e horários de trabalho de cada um. Necessário para a sincronização da agenda de cada profissional com o Google Calendar.
            </p>
          </button>
        </div>

        {schedulingMode === "per_professional" && (
          <div className="flex items-start gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3">
            <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
            <p className="text-xs text-amber-200/90 font-sans leading-relaxed">
              Neste modo, um serviço só fica disponível para agendamento se tiver{" "}
              <strong className="font-semibold">pelo menos um profissional vinculado</strong> a ele. Vá em{" "}
              <strong className="font-semibold">Equipe → configurar profissional</strong> para definir os serviços e os horários de trabalho de cada um.
            </p>
          </div>
        )}

        <div className="h-4">
          {modeSaving && (
            <span className="text-xs text-muted-foreground flex items-center gap-1.5">
              <Loader2 className="h-3 w-3 animate-spin" /> Salvando...
            </span>
          )}
          {modeSaved && (
            <span className="text-xs text-emerald-400 font-sans font-semibold">Modo de agendamento salvo!</span>
          )}
        </div>
      </div>

      <div className="grid gap-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="grid gap-1.5">
            <Label htmlFor="model" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Modelo de IA</Label>
            <div className="relative">
              <Bot className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
              <Input id="model" {...register("model")} className="h-11 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
            </div>
            {errors.model && <p className="text-xs text-destructive font-sans font-medium">{errors.model.message as string}</p>}
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="temperature" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Temperatura (0 a 2)</Label>
            <div className="relative">
              <SlidersHorizontal className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
              <Input id="temperature" type="number" step="0.1" {...register("temperature")} className="h-11 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
            </div>
            {errors.temperature && <p className="text-xs text-destructive font-sans font-medium">{errors.temperature.message as string}</p>}
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="max_output_tokens" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Max Tokens</Label>
            <div className="relative">
              <MessageSquare className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
              <Input id="max_output_tokens" type="number" {...register("max_output_tokens")} className="h-11 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
            </div>
            {errors.max_output_tokens && <p className="text-xs text-destructive font-sans font-medium">{errors.max_output_tokens.message as string}</p>}
          </div>
        </div>

        <div className="flex flex-row items-center justify-between rounded-2xl border border-white/10 p-4 bg-white/5 shadow-md">
          <div className="space-y-0.5">
            <Label className="font-heading text-sm font-semibold text-foreground flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary animate-pulse" />
              IA Multimodal (Áudio, Imagem e Documentos)
            </Label>
            <p className="text-xs text-muted-foreground/80 font-sans mt-0.5 leading-relaxed">
              Permite que a Sofia interprete áudios (até 1m30s), imagens, vídeos e documentos enviados pelos pacientes. Aumenta o custo por mensagem.
            </p>
          </div>
          <Controller
            name="multimodal_enabled"
            control={control}
            render={({ field }) => (
              <Switch checked={field.value} onCheckedChange={field.onChange} className="cursor-pointer" />
            )}
          />
        </div>

        <div className="flex flex-row items-center justify-between rounded-2xl border border-white/10 p-4 bg-white/5 shadow-md">
          <div className="space-y-0.5">
            <Label className="font-heading text-sm font-semibold text-foreground flex items-center gap-2">
              <Layers className="h-4 w-4 text-primary" />
              Atendimento por especialistas (beta)
            </Label>
            <p className="text-xs text-muted-foreground/80 font-sans mt-0.5 leading-relaxed">
              Em vez de uma Sofia única, o atendimento é dividido: uma parte cuida da agenda e
              outra apresenta procedimentos e preços. Cada uma recebe instruções mais focadas,
              o que tende a deixar as respostas mais precisas. Em compensação, <strong className="font-semibold">custa
              de 2 a 3 vezes mais por mensagem</strong> e leva um pouco mais de tempo para responder.
              Recomendado ativar primeiro em uma clínica de teste.
            </p>
          </div>
          <Controller
            name="multi_agent_enabled"
            control={control}
            render={({ field }) => (
              <Switch checked={field.value} onCheckedChange={field.onChange} className="cursor-pointer" />
            )}
          />
        </div>
      </div>

      <div className="flex items-center gap-4 pt-4 border-t border-white/5">
        <button type="submit" disabled={isPending} className="sofia-btn-gradient px-5 py-2.5 rounded-xl text-white font-bold text-xs shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center disabled:opacity-50">
          {isPending ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="mr-1.5 h-3.5 w-3.5" />
          )}
          Salvar Inteligência Artificial
        </button>
        {isSuccess && <span className="text-xs text-emerald-400 font-sans font-semibold">Configurações salvas com sucesso!</span>}
      </div>
    </form>
  );
}

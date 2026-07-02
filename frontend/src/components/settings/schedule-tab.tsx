"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { TenantProfile, useUpdateTenant } from "@/hooks/useSettings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { 
  Globe, 
  Clock, 
  Save, 
  Loader2, 
  Plus, 
  X, 
  CalendarDays, 
  Sparkles, 
  ArrowRight 
} from "lucide-react";

// For working days: 1=Seg, ..., 7=Dom. In TS/JS usually 0=Dom. We'll use 1-7 as defined in python backend.
// Accepts "HH:MM" and "HH:MM:SS" (browser may include seconds), normalises to "HH:MM"
const timeString = z
  .string()
  .transform((v) => v.slice(0, 5))
  .pipe(z.string().regex(/^([01]\d|2[0-3]):([0-5]\d)$/, "Use o formato HH:MM"));

const optionalTime = z
  .string()
  .transform((v) => v.slice(0, 5))
  .pipe(z.string().regex(/^([01]\d|2[0-3]):([0-5]\d)$/, "Use o formato HH:MM").or(z.literal("")));

const formSchema = z.object({
  timezone: z.string().min(1, "Obrigatório"),
  open_time: timeString,
  close_time: timeString,
  lunch_start: optionalTime,
  lunch_end: optionalTime,
  slot_granularity_minutes: z.coerce.number().min(5).max(120),
});

type FormValues = z.infer<typeof formSchema>;

export function ScheduleTab({ tenant }: { tenant: TenantProfile }) {
  const { mutateAsync: updateTenant, isPending } = useUpdateTenant();
  const [isSuccess, setIsSuccess] = useState(false);
  const [workingDays, setWorkingDays] = useState<number[]>(
    tenant.settings?.schedule?.working_days || [1, 2, 3, 4, 5]
  );

  const defaultValues = tenant.settings?.schedule || {
    timezone: "America/Sao_Paulo",
    open_time: "08:00",
    close_time: "18:00",
    lunch_start: "12:00",
    lunch_end: "13:00",
    slot_granularity_minutes: 30,
  };

  const { register, handleSubmit, watch, formState: { errors } } = useForm<z.infer<typeof formSchema>>({
    resolver: zodResolver(formSchema) as any,
    defaultValues: {
      timezone: defaultValues.timezone || "America/Sao_Paulo",
      open_time: defaultValues.open_time || "08:00",
      close_time: defaultValues.close_time || "18:00",
      lunch_start: defaultValues.lunch_start || "",
      lunch_end: defaultValues.lunch_end || "",
      slot_granularity_minutes: defaultValues.slot_granularity_minutes || 30,
    },
  });

  const currentOpenTime = watch("open_time") || defaultValues.open_time;
  const currentCloseTime = watch("close_time") || defaultValues.close_time;
  const currentLunchStart = watch("lunch_start") || defaultValues.lunch_start;
  const currentLunchEnd = watch("lunch_end") || defaultValues.lunch_end;

  const toggleDay = (day: number) => {
    setWorkingDays(prev => 
      prev.includes(day) ? prev.filter(d => d !== day) : [...prev, day].sort()
    );
  };

  const onSubmit = async (data: FormValues) => {
    try {
      setIsSuccess(false);
      await updateTenant({
        settings: {
          ...tenant.settings,
          schedule: {
            timezone: data.timezone,
            working_days: workingDays,
            open_time: data.open_time,
            close_time: data.close_time,
            lunch_start: data.lunch_start || undefined,
            lunch_end: data.lunch_end || undefined,
            slot_granularity_minutes: data.slot_granularity_minutes,
          }
        }
      });
      setIsSuccess(true);
      setTimeout(() => setIsSuccess(false), 3000);
    } catch (error) {
      console.error("Failed to update schedule settings", error);
    }
  };

  const daysOfWeek = [
    { value: 1, label: "Seg", full: "Segunda-feira" },
    { value: 2, label: "Ter", full: "Terça-feira" },
    { value: 3, label: "Qua", full: "Quarta-feira" },
    { value: 4, label: "Qui", full: "Quinta-feira" },
    { value: 5, label: "Sex", full: "Sexta-feira" },
    { value: 6, label: "Sáb", full: "Sábado" },
    { value: 7, label: "Dom", full: "Domingo" },
  ];

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="w-full">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        
        {/* Left Column: Configuration Area */}
        <div className="lg:col-span-8 space-y-6">
          
          {/* Global Configurations & Expediente */}
          <section className="glass-panel rounded-3xl p-8 border border-white/10 bg-white/[0.02] shadow-2xl space-y-6">
            <div className="flex items-start gap-4 mb-4">
              <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center text-primary shrink-0 border border-primary/20">
                <Clock className="h-6 w-6 text-primary" />
              </div>
              <div>
                <h3 className="font-heading text-lg font-bold text-foreground">Configuração da Agenda</h3>
                <p className="text-xs text-muted-foreground/80 font-sans mt-0.5">
                  Defina os parâmetros globais e o horário de funcionamento padrão da clínica.
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Timezone */}
              <div className="grid gap-1.5">
                <Label htmlFor="timezone" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Fuso Horário (Timezone)</Label>
                <div className="relative">
                  <Globe className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
                  <Input id="timezone" {...register("timezone")} className="h-12 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" placeholder="America/Sao_Paulo" />
                </div>
                {errors.timezone && <p className="text-xs text-destructive font-sans font-medium">{errors.timezone.message as string}</p>}
              </div>

              {/* Granularidade */}
              <div className="grid gap-1.5">
                <Label htmlFor="slot_granularity_minutes" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Granularidade da Grade (minutos)</Label>
                <div className="relative">
                  <Clock className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
                  <Input id="slot_granularity_minutes" type="number" {...register("slot_granularity_minutes")} className="h-12 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
                </div>
                {errors.slot_granularity_minutes && <p className="text-xs text-destructive font-sans font-medium">{errors.slot_granularity_minutes.message as string}</p>}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4 border-t border-white/5">
              {/* Expediente */}
              <div className="space-y-4">
                <h4 className="font-heading text-sm font-semibold text-foreground">Horário de Expediente Padrão</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div className="grid gap-1.5">
                    <Label htmlFor="open_time" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Abertura</Label>
                    <Input id="open_time" type="time" {...register("open_time")} className="h-12 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
                    {errors.open_time && <p className="text-xs text-destructive font-sans font-medium">{errors.open_time.message as string}</p>}
                  </div>
                  <div className="grid gap-1.5">
                    <Label htmlFor="close_time" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Fechamento</Label>
                    <Input id="close_time" type="time" {...register("close_time")} className="h-12 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
                    {errors.close_time && <p className="text-xs text-destructive font-sans font-medium">{errors.close_time.message as string}</p>}
                  </div>
                </div>
              </div>

              {/* Horário de Almoço */}
              <div className="space-y-4">
                <h4 className="font-heading text-sm font-semibold text-foreground">Horário de Almoço (opcional)</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div className="grid gap-1.5">
                    <Label htmlFor="lunch_start" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Início</Label>
                    <Input id="lunch_start" type="time" {...register("lunch_start")} className="h-12 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
                  </div>
                  <div className="grid gap-1.5">
                    <Label htmlFor="lunch_end" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Término</Label>
                    <Input id="lunch_end" type="time" {...register("lunch_end")} className="h-12 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
                  </div>
                </div>
                {(errors.lunch_start || errors.lunch_end) && (
                  <p className="text-xs text-destructive font-sans font-medium">Formato de hora inválido</p>
                )}
              </div>
            </div>
          </section>

          {/* Horário de Funcionamento Card */}
          <section className="glass-panel rounded-3xl p-8 border border-white/10 bg-white/[0.02] shadow-2xl space-y-6">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center text-primary shrink-0 border border-primary/20">
                <Clock className="h-6 w-6 text-primary" />
              </div>
              <div>
                <h3 className="font-heading text-lg font-bold text-foreground">Dias de Funcionamento</h3>
                <p className="text-xs text-muted-foreground/80 font-sans mt-0.5">
                  Defina os períodos em que a clínica está aberta para atendimento. A Sofia usará esses horários para sugerir agendamentos de forma inteligente.
                </p>
              </div>
            </div>

            <div className="space-y-4 pt-4 border-t border-white/5">
              {daysOfWeek.map(day => {
                const isActive = workingDays.includes(day.value);
                return (
                  <div 
                    key={day.value}
                    className={`flex flex-col sm:flex-row sm:items-center justify-between p-4 rounded-2xl border transition-all ${
                      isActive 
                        ? "bg-white/[0.02] border-white/10 hover:bg-white/[0.04]" 
                        : "bg-white/[0.01] border-white/5 opacity-60"
                    }`}
                  >
                    <div className="flex items-center gap-4 min-w-[180px]">
                      <Switch
                        checked={isActive}
                        onCheckedChange={() => toggleDay(day.value)}
                        className="cursor-pointer"
                      />
                      <span className={`font-heading text-sm font-semibold ${isActive ? "text-foreground" : "text-muted-foreground"}`}>
                        {day.full}
                      </span>
                    </div>
                    
                    <div className="flex items-center gap-2 mt-2 sm:mt-0">
                      {isActive ? (
                        <div className="flex items-center gap-2 text-xs text-muted-foreground bg-primary/5 px-3 py-1.5 rounded-xl border border-primary/10">
                          <Clock className="h-3.5 w-3.5 text-primary" />
                          <span>
                            {currentOpenTime} às {currentLunchStart || currentCloseTime}
                            {currentLunchEnd && ` • ${currentLunchEnd} às ${currentCloseTime}`}
                          </span>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground/75 italic">
                          Fechado para atendimentos
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Holidays & Special Dates Section */}
          <section className="glass-panel rounded-3xl p-8 border border-white/10 bg-white/[0.02] shadow-2xl space-y-6">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <CalendarDays className="h-6 w-6 text-primary animate-pulse" />
                <h3 className="font-heading text-lg font-bold text-foreground">Feriados e Datas Especiais</h3>
              </div>
              <button
                type="button"
                className="px-4 py-2 border border-primary text-primary hover:bg-primary/10 rounded-xl transition-all text-xs font-semibold flex items-center gap-1.5 cursor-pointer"
              >
                <Plus className="h-4 w-4" />
                Adicionar Data
              </button>
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between p-4 bg-white/[0.01] rounded-2xl border border-white/5">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-white/5 flex flex-col items-center justify-center border border-white/10 shrink-0">
                    <span className="text-[9px] font-bold text-primary uppercase">Set</span>
                    <span className="text-sm font-bold text-foreground leading-none">07</span>
                  </div>
                  <div>
                    <p className="font-heading text-sm font-semibold text-foreground">Independência do Brasil</p>
                    <p className="text-[10px] text-muted-foreground">Status: <span className="text-rose-400 font-semibold">Clínica Fechada</span></p>
                  </div>
                </div>
                <button type="button" className="text-muted-foreground hover:text-rose-400 transition-colors">
                  <X className="h-4 w-4" />
                </button>
              </div>
              
              <div className="flex items-center justify-between p-4 bg-white/[0.01] rounded-2xl border border-white/5">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-white/5 flex flex-col items-center justify-center border border-white/10 shrink-0">
                    <span className="text-[9px] font-bold text-primary uppercase">Out</span>
                    <span className="text-sm font-bold text-foreground leading-none">12</span>
                  </div>
                  <div>
                    <p className="font-heading text-sm font-semibold text-foreground">Nossa Sra. Aparecida</p>
                    <p className="text-[10px] text-muted-foreground">Status: <span className="text-rose-400 font-semibold">Clínica Fechada</span></p>
                  </div>
                </div>
                <button type="button" className="text-muted-foreground hover:text-rose-400 transition-colors">
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          </section>

        </div>

        {/* Right Column: Sidebar */}
        <div className="lg:col-span-4 space-y-6">
          
          {/* IA Suggestion Card */}
          <div className="glass-panel rounded-3xl p-6 border border-primary/20 bg-primary/5 relative overflow-hidden shadow-2xl">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-8 h-8 rounded-lg bg-primary/20 flex items-center justify-center text-primary">
                <Sparkles className="h-4 w-4 text-primary" />
              </div>
              <h4 className="font-heading text-sm font-semibold text-primary">Dica da Sofia</h4>
            </div>
            <p className="text-xs text-muted-foreground/80 mb-4 leading-relaxed font-sans">
              Notei que suas segundas-feiras costumam ter alta demanda. Recomendo estender o horário até as 19:00 para reduzir a fila de espera.
            </p>
            <button
              type="button"
              className="w-full py-2.5 bg-primary/10 border border-primary/30 text-primary rounded-xl text-xs font-bold hover:bg-primary hover:text-primary-foreground transition-all cursor-pointer"
            >
              Aplicar Sugestão
            </button>
          </div>

          {/* Statistics Card */}
          <div className="glass-panel rounded-3xl p-6 border border-white/10 bg-white/[0.02] shadow-2xl">
            <h4 className="font-heading text-sm font-bold text-foreground mb-6">Resumo de Atendimento</h4>
            <div className="space-y-4">
              <div className="flex justify-between items-center py-2 border-b border-white/5 text-xs">
                <span className="text-muted-foreground">Carga Horária Semanal</span>
                <span className="text-foreground font-bold">48 horas</span>
              </div>
              <div className="flex justify-between items-center py-2 border-b border-white/5 text-xs">
                <span className="text-muted-foreground">Média de Pacientes/Dia</span>
                <span className="text-foreground font-bold">14</span>
              </div>
              <div className="flex justify-between items-center py-2 border-b border-white/5 text-xs">
                <span className="text-muted-foreground">Turnos Cadastrados</span>
                <span className="text-foreground font-bold">8</span>
              </div>
            </div>
            <div className="mt-8 pt-4">
              <p className="text-[10px] text-muted-foreground uppercase tracking-widest font-mono mb-4">
                Eficiência de Agenda
              </p>
              <div className="w-full bg-white/10 rounded-full h-2 mb-2">
                <div className="bg-primary h-2 rounded-full" style={{ width: "82%" }}></div>
              </div>
              <p className="text-[10px] text-right text-primary font-bold">82% OCUPADA</p>
            </div>
          </div>

          {/* Help Card */}
          <div className="p-6 rounded-3xl bg-white/[0.01] border border-dashed border-white/10 shadow-2xl">
            <h4 className="text-xs font-bold text-foreground mb-2">Dúvidas sobre horários?</h4>
            <p className="text-[11px] text-muted-foreground mb-4 leading-relaxed font-sans">
              Saiba como configurar feriados móveis ou pausas de almoço personalizadas em nossa central.
            </p>
            <a className="text-primary text-xs font-bold hover:underline flex items-center gap-1 cursor-pointer" href="#">
              Ver Tutorial
              <ArrowRight className="h-3 w-3" />
            </a>
          </div>

        </div>

        {/* Global Save Button */}
        <div className="flex items-center gap-4 pt-4 border-t border-white/5 lg:col-span-12 w-full mt-6">
          <button 
            type="submit" 
            disabled={isPending} 
            className="sofia-btn-gradient px-5 py-2.5 rounded-xl text-white font-bold text-xs shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center disabled:opacity-50"
          >
            {isPending ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="mr-1.5 h-3.5 w-3.5" />
            )}
            Salvar Horários
          </button>
          {isSuccess && <span className="text-xs text-emerald-400 font-sans font-semibold">Horários salvos com sucesso!</span>}
        </div>

      </div>
    </form>
  );
}

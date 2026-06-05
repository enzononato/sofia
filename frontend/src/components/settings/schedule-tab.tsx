"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { TenantProfile, useUpdateTenant } from "@/hooks/useSettings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Globe, Clock, Save, Loader2 } from "lucide-react";

// For working days: 1=Seg, ..., 7=Dom. In TS/JS usually 0=Dom. We'll use 1-7 as defined in python backend.
const formSchema = z.object({
  timezone: z.string().min(1, "Obrigatório"),
  open_time: z.string().regex(/^([01]\d|2[0-3]):([0-5]\d)$/, "Use o formato HH:MM"),
  close_time: z.string().regex(/^([01]\d|2[0-3]):([0-5]\d)$/, "Use o formato HH:MM"),
  lunch_start: z.string().regex(/^([01]\d|2[0-3]):([0-5]\d)$/, "Use o formato HH:MM").optional().or(z.literal("")),
  lunch_end: z.string().regex(/^([01]\d|2[0-3]):([0-5]\d)$/, "Use o formato HH:MM").optional().or(z.literal("")),
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

  const { register, handleSubmit, formState: { errors } } = useForm<z.infer<typeof formSchema>>({
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
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-8 max-w-2xl">
      <div>
        <h3 className="text-lg font-medium">Horários de Funcionamento</h3>
        <p className="text-sm text-muted-foreground mt-1">
          A IA usa essas regras para não marcar compromissos fora do expediente ou no horário de almoço.
        </p>
      </div>

      <div className="grid gap-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="grid gap-3">
            <Label htmlFor="timezone">Fuso Horário (Timezone)</Label>
            <div className="relative">
              <Globe className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <Input id="timezone" {...register("timezone")} className="pl-9" placeholder="America/Sao_Paulo" />
            </div>
            {errors.timezone && <p className="text-sm text-destructive">{errors.timezone.message}</p>}
          </div>

          <div className="grid gap-3">
            <Label htmlFor="slot_granularity_minutes">Granularidade da Grade (minutos)</Label>
            <div className="relative">
              <Clock className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <Input id="slot_granularity_minutes" type="number" {...register("slot_granularity_minutes")} className="pl-9" />
            </div>
            {errors.slot_granularity_minutes && <p className="text-sm text-destructive">{errors.slot_granularity_minutes.message}</p>}
          </div>
        </div>

        <div className="space-y-3">
          <Label>Dias Úteis</Label>
          <div className="flex flex-wrap gap-2">
            {daysOfWeek.map(day => {
              const isActive = workingDays.includes(day.value);
              return (
                <button
                  key={day.value}
                  type="button"
                  onClick={() => toggleDay(day.value)}
                  className={`px-4 py-2 rounded-full text-sm font-medium transition-colors border ${
                    isActive 
                      ? "bg-primary text-primary-foreground border-primary" 
                      : "bg-background text-muted-foreground border-border/50 hover:bg-muted"
                  }`}
                  title={day.full}
                >
                  {day.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 p-5 rounded-xl border border-border/50 bg-card/50">
          <div className="space-y-4">
            <h4 className="font-medium text-sm">Expediente</h4>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label htmlFor="open_time" className="text-xs">Abertura</Label>
                <Input id="open_time" type="time" {...register("open_time")} />
                {errors.open_time && <p className="text-xs text-destructive">{errors.open_time.message}</p>}
              </div>
              <div className="grid gap-2">
                <Label htmlFor="close_time" className="text-xs">Fechamento</Label>
                <Input id="close_time" type="time" {...register("close_time")} />
                {errors.close_time && <p className="text-xs text-destructive">{errors.close_time.message}</p>}
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <h4 className="font-medium text-sm">Horário de Almoço (opcional)</h4>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label htmlFor="lunch_start" className="text-xs">Início</Label>
                <Input id="lunch_start" type="time" {...register("lunch_start")} />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="lunch_end" className="text-xs">Término</Label>
                <Input id="lunch_end" type="time" {...register("lunch_end")} />
              </div>
            </div>
            {(errors.lunch_start || errors.lunch_end) && (
              <p className="text-xs text-destructive">Formato de hora inválido</p>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-4 pt-4">
        <Button type="submit" disabled={isPending}>
          {isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          Salvar Horários
        </Button>
        {isSuccess && <span className="text-sm text-emerald-500 font-medium">Horários salvos com sucesso!</span>}
      </div>
    </form>
  );
}

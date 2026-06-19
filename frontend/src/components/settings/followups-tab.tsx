"use client";

import { useState } from "react";
import { TenantProfile, useUpdateTenant } from "@/hooks/useSettings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { BellRing, Loader2, Save, MessageCircleHeart } from "lucide-react";

export function FollowupsTab({ tenant }: { tenant: TenantProfile }) {
  const { mutateAsync: updateTenant, isPending } = useUpdateTenant();
  const [isSuccess, setIsSuccess] = useState(false);

  const f = tenant.settings?.followups || {};

  const [remindersEnabled, setRemindersEnabled] = useState<boolean>(f.reminders_enabled ?? true);
  const [reminderHours, setReminderHours] = useState<string>((f.reminder_hours ?? [24, 2]).join(", "));
  const [reengageEnabled, setReengageEnabled] = useState<boolean>(f.reengagement_enabled ?? true);
  const [afterDays, setAfterDays] = useState<string>(String(f.reengage_after_days ?? 3));
  const [cooldownDays, setCooldownDays] = useState<string>(String(f.reengage_cooldown_days ?? 7));
  const [error, setError] = useState<string | null>(null);

  const parseHours = (raw: string): number[] =>
    raw
      .split(",")
      .map((s) => parseInt(s.trim(), 10))
      .filter((n) => Number.isFinite(n) && n > 0 && n <= 72)
      .sort((a, b) => b - a);

  const handleSave = async () => {
    setError(null);
    const hours = parseHours(reminderHours);
    if (remindersEnabled && hours.length === 0) {
      setError("Informe ao menos uma janela de lembrete válida (1 a 72 horas).");
      return;
    }
    try {
      setIsSuccess(false);
      await updateTenant({
        settings: {
          followups: {
            reminders_enabled: remindersEnabled,
            reminder_hours: hours,
            reengagement_enabled: reengageEnabled,
            reengage_after_days: Math.max(1, parseInt(afterDays, 10) || 3),
            reengage_cooldown_days: Math.max(1, parseInt(cooldownDays, 10) || 7),
          },
        },
      });
      setReminderHours(hours.join(", "));
      setIsSuccess(true);
      setTimeout(() => setIsSuccess(false), 3000);
    } catch {
      setError("Erro ao salvar. Tente novamente.");
    }
  };

  return (
    <div className="space-y-8 max-w-2xl">
      <div>
        <h3 className="text-lg font-medium">Lembretes e Follow-up automático</h3>
        <p className="text-sm text-muted-foreground mt-1">
          Defina quando a Sofia lembra os pacientes dos agendamentos e quando reengaja quem parou de responder.
        </p>
      </div>

      {/* Reminders */}
      <div className="rounded-xl border border-border/50 p-5 space-y-4 bg-card/50">
        <div className="flex items-center justify-between">
          <Label className="text-base flex items-center gap-2">
            <BellRing className="h-4 w-4 text-amber-500" />
            Lembretes de agendamento
          </Label>
          <Switch checked={remindersEnabled} onCheckedChange={setRemindersEnabled} />
        </div>
        <p className="text-sm text-muted-foreground">
          A Sofia envia um lembrete automático antes de cada agendamento confirmado.
        </p>
        <div className="grid gap-2">
          <Label htmlFor="reminder_hours">Horas antes do agendamento (separadas por vírgula)</Label>
          <Input
            id="reminder_hours"
            value={reminderHours}
            onChange={(e) => setReminderHours(e.target.value)}
            placeholder="24, 2"
            disabled={!remindersEnabled}
          />
          <p className="text-xs text-muted-foreground">
            Ex.: <code>24, 2</code> envia um lembrete 24h e outro 2h antes. Máximo 72 horas por janela.
          </p>
        </div>
      </div>

      {/* Re-engagement */}
      <div className="rounded-xl border border-border/50 p-5 space-y-4 bg-card/50">
        <div className="flex items-center justify-between">
          <Label className="text-base flex items-center gap-2">
            <MessageCircleHeart className="h-4 w-4 text-primary" />
            Reengajar pacientes inativos
          </Label>
          <Switch checked={reengageEnabled} onCheckedChange={setReengageEnabled} />
        </div>
        <p className="text-sm text-muted-foreground">
          A Sofia volta a falar com pacientes que pararam de responder (apenas leads e conversas em andamento).
        </p>
        <div className="grid grid-cols-2 gap-4">
          <div className="grid gap-2">
            <Label htmlFor="after_days">Reengajar após (dias sem resposta)</Label>
            <Input
              id="after_days"
              type="number"
              min={1}
              value={afterDays}
              onChange={(e) => setAfterDays(e.target.value)}
              disabled={!reengageEnabled}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="cooldown_days">Intervalo mínimo entre follow-ups (dias)</Label>
            <Input
              id="cooldown_days"
              type="number"
              min={1}
              value={cooldownDays}
              onChange={(e) => setCooldownDays(e.target.value)}
              disabled={!reengageEnabled}
            />
          </div>
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="flex items-center gap-4">
        <Button onClick={handleSave} disabled={isPending}>
          {isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
          Salvar Follow-up
        </Button>
        {isSuccess && <span className="text-sm text-emerald-500 font-medium">Configurações salvas!</span>}
      </div>
    </div>
  );
}

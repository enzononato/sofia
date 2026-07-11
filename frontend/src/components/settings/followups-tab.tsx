"use client";

import { useState } from "react";
import { TenantProfile, useUpdateTenant } from "@/hooks/useSettings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  BellRing,
  Loader2,
  Save,
  MessageCircleHeart,
  Lightbulb,
  MessageSquare,
  Mail,
  Sparkles,
  Info,
  UserCheck,
} from "lucide-react";

export function FollowupsTab({ tenant }: { tenant: TenantProfile }) {
  const { mutateAsync: updateTenant, isPending } = useUpdateTenant();
  const [isSuccess, setIsSuccess] = useState(false);

  const f = tenant.settings?.followups || {};

  const [remindersEnabled, setRemindersEnabled] = useState<boolean>(f.reminders_enabled ?? true);
  const [reminderHours, setReminderHours] = useState<string>((f.reminder_hours ?? [24, 2]).join(", "));
  const [reengageEnabled, setReengageEnabled] = useState<boolean>(f.reengagement_enabled ?? true);
  const [afterDays, setAfterDays] = useState<string>(String(f.reengage_after_days ?? 3));
  const [cooldownDays, setCooldownDays] = useState<string>(String(f.reengage_cooldown_days ?? 7));
  // Alert e-mail to the clinic when Sofia hands a conversation off to a human
  // (fresh handoff + the "still waiting" follow-up alert). Default on.
  const [handoffAlertEnabled, setHandoffAlertEnabled] = useState<boolean>(
    f.handoff_alert_email_enabled ?? true
  );
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
            handoff_alert_email_enabled: handoffAlertEnabled,
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
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 w-full items-start">
      {/* Left Column: Main Configuration Area */}
      <div className="lg:col-span-8 space-y-6">
        
        {/* Reminder Section */}
        <section className="glass-panel rounded-3xl p-8 border border-white/10 bg-white/[0.02] shadow-2xl transition-all hover:border-primary/20">
          <div className="flex items-start justify-between mb-8">
            <div className="flex gap-4">
              <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center text-primary shrink-0 border border-primary/20">
                <BellRing className="h-6 w-6 text-primary animate-pulse" />
              </div>
              <div>
                <h3 className="font-heading text-lg font-bold text-foreground">Lembretes de Consulta</h3>
                <p className="text-xs text-muted-foreground/80 font-sans mt-0.5">
                  Envio automático via WhatsApp e E-mail.
                </p>
              </div>
            </div>
            <Switch 
              checked={remindersEnabled} 
              onCheckedChange={setRemindersEnabled} 
              className="cursor-pointer" 
            />
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="space-y-4">
              <div className="grid gap-2">
                <Label htmlFor="reminder_hours" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">
                  Janelas de Lembrete (horas antes, separadas por vírgula)
                </Label>
                <div className="relative">
                  <Input
                    id="reminder_hours"
                    value={reminderHours}
                    onChange={(e) => setReminderHours(e.target.value)}
                    placeholder="24, 2"
                    disabled={!remindersEnabled}
                    className="h-12 pl-4 rounded-xl border border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full"
                  />
                </div>
                <p className="text-[10px] text-muted-foreground/60 font-sans mt-0.5">
                  Ex.: <code className="font-mono bg-white/5 border border-white/5 rounded px-1 py-0.5 text-[9px]">24, 2</code> envia um lembrete 24h e outro 2h antes. Máximo 72 horas por janela.
                </p>
              </div>
            </div>
            
            <div className="space-y-4">
              <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block mb-2">
                Canal de envio prioritário
              </p>
              <div className="flex gap-4">
                <button
                  type="button"
                  className="flex-1 py-3 px-4 bg-primary/15 border border-primary/30 text-primary rounded-xl flex items-center justify-center gap-2 text-xs font-bold transition-all hover:bg-primary/25"
                >
                  <MessageSquare className="h-4 w-4" />
                  WhatsApp
                </button>
                <button
                  type="button"
                  className="flex-1 py-3 px-4 bg-white/5 border border-white/10 text-muted-foreground rounded-xl flex items-center justify-center gap-2 text-xs font-semibold hover:bg-white/10 hover:text-foreground transition-all"
                >
                  <Mail className="h-4 w-4" />
                  E-mail
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* Re-engagement Section */}
        <section className="glass-panel rounded-3xl p-8 border border-white/10 bg-white/[0.02] shadow-2xl transition-all hover:border-[#fbabff]/20 relative overflow-hidden">
          <div className="absolute -top-12 -right-12 w-32 h-32 bg-[#fbabff]/5 blur-3xl pointer-events-none rounded-full" />
          <div className="flex items-start justify-between mb-8">
            <div className="flex gap-4">
              <div className="w-12 h-12 rounded-2xl bg-[#fbabff]/10 flex items-center justify-center text-[#fbabff] shrink-0 border border-[#fbabff]/20">
                <MessageCircleHeart className="h-6 w-6 text-[#fbabff]" />
              </div>
              <div>
                <h3 className="font-heading text-lg font-bold text-foreground">Reengajamento de Leads</h3>
                <p className="text-xs text-muted-foreground/80 font-sans mt-0.5">
                  Recuperação inteligente de pacientes inativos.
                </p>
              </div>
            </div>
            <Switch 
              checked={reengageEnabled} 
              onCheckedChange={setReengageEnabled} 
              className="cursor-pointer" 
            />
          </div>
          
          <div className="p-6 bg-white/[0.02] rounded-2xl border border-white/5">
            <div className="flex flex-col md:flex-row md:items-center gap-6">
              <div className="flex-1 space-y-4">
                <div>
                  <Label className="block font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 mb-3">CONDIÇÃO DE DISPARO</Label>
                  <div className="flex items-center gap-3 text-sm text-foreground">
                    <span>Se o lead não responde há</span>
                    <Input
                      type="number"
                      min={1}
                      value={afterDays}
                      onChange={(e) => setAfterDays(e.target.value)}
                      disabled={!reengageEnabled}
                      className="w-20 bg-background/55 border border-white/10 rounded-xl px-2 py-2 text-center text-[#fbabff] font-bold focus:ring-1 focus:ring-[#fbabff]/50 focus:border-[#fbabff]/50 outline-none h-11"
                    />
                    <span>dias</span>
                  </div>
                </div>
                
                <div>
                  <Label className="block font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 mb-3">INTERVALO MÍNIMO ENTRE FOLLOW-UPS</Label>
                  <div className="flex items-center gap-3 text-sm text-foreground">
                    <span>Esperar pelo menos</span>
                    <Input
                      type="number"
                      min={1}
                      value={cooldownDays}
                      onChange={(e) => setCooldownDays(e.target.value)}
                      disabled={!reengageEnabled}
                      className="w-20 bg-background/55 border border-white/10 rounded-xl px-2 py-2 text-center text-[#fbabff] font-bold focus:ring-1 focus:ring-[#fbabff]/50 focus:border-[#fbabff]/50 outline-none h-11"
                    />
                    <span>dias antes de reengajar novamente</span>
                  </div>
                </div>
              </div>
              
              <div className="flex-1 self-start md:self-center">
                <Label className="block font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 mb-3">AÇÃO DA SOFIA</Label>
                <div className="flex items-center gap-3 p-4 bg-[#fbabff]/5 border border-[#fbabff]/20 rounded-xl">
                  <Sparkles className="h-5 w-5 text-[#fbabff] shrink-0" />
                  <span className="text-xs italic text-foreground/90">"Enviar mensagem personalizada de acompanhamento"</span>
                </div>
              </div>
            </div>
          </div>
          
          <div className="mt-8 flex items-center gap-3 text-[10px] text-muted-foreground/80 font-sans">
            <Info className="h-4 w-4 text-muted-foreground/60 shrink-0" />
            <span>Sofia utiliza Processamento de Linguagem Natural para adaptar o tom de voz ao histórico do paciente.</span>
          </div>
        </section>

        {/* Handoff Alert Section */}
        <section className="glass-panel rounded-3xl p-8 border border-white/10 bg-white/[0.02] shadow-2xl transition-all hover:border-amber-500/20">
          <div className="flex items-start justify-between mb-4">
            <div className="flex gap-4">
              <div className="w-12 h-12 rounded-2xl bg-amber-500/10 flex items-center justify-center text-amber-400 shrink-0 border border-amber-500/20">
                <UserCheck className="h-6 w-6 text-amber-400" />
              </div>
              <div>
                <h3 className="font-heading text-lg font-bold text-foreground">Alerta de Atendimento Humano</h3>
                <p className="text-xs text-muted-foreground/80 font-sans mt-0.5">
                  Avisa por e-mail quando a Sofia transfere uma conversa para a equipe — e novamente se ninguém responder a tempo.
                </p>
              </div>
            </div>
            <Switch
              checked={handoffAlertEnabled}
              onCheckedChange={setHandoffAlertEnabled}
              className="cursor-pointer"
            />
          </div>
          <div className="flex items-center gap-3 text-[10px] text-muted-foreground/80 font-sans">
            <Mail className="h-4 w-4 text-muted-foreground/60 shrink-0" />
            <span>Enviado para o e-mail cadastrado da clínica.</span>
          </div>
        </section>

      </div>

      {/* Right Column: Sidebar Info/Tips Area */}
      <div className="lg:col-span-4 space-y-6">
        
        {/* Dica da Sofia */}
        <div className="glass-panel rounded-3xl p-6 border border-primary/20 bg-primary/5 relative overflow-hidden">
          <h4 className="font-heading text-sm font-semibold text-primary mb-4 flex items-center gap-2">
            <Lightbulb className="h-4 w-4 text-primary" />
            Dica da Sofia
          </h4>
          <p className="text-xs text-muted-foreground/80 leading-relaxed mb-6 font-sans">
            Clínicas que utilizam o lembrete de <strong className="text-primary font-bold">2 horas</strong> reduzem o "No-show" em até <strong className="text-primary font-bold">34%</strong>. Considere ativar este canal para otimizar sua agenda.
          </p>
        </div>

        {/* Resumo da Atividade */}
        <div className="glass-panel rounded-3xl p-6 border border-white/10 bg-white/[0.02] space-y-4">
          <h4 className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80">Resumo da Atividade</h4>
          <div className="space-y-4">
            <div className="flex justify-between items-center text-xs">
              <span className="text-muted-foreground">Lembretes hoje</span>
              <span className="font-mono text-xs font-semibold text-primary bg-primary/10 px-2 py-1 rounded">128</span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-muted-foreground">Leads reengajados</span>
              <span className="font-mono text-xs font-semibold text-[#fbabff] bg-[#fbabff]/10 px-2 py-1 rounded">12</span>
            </div>
            <div className="pt-4 border-t border-white/5">
              <div className="w-full h-2 bg-white/10 rounded-full overflow-hidden">
                <div className="w-3/4 h-full bg-gradient-to-r from-primary to-[#fbabff]"></div>
              </div>
              <p className="text-[10px] text-muted-foreground/60 mt-2 text-center">Eficiência das Automações: 75%</p>
            </div>
          </div>
        </div>

        {/* Previsualização WhatsApp */}
        <div className="glass-panel rounded-3xl p-6 border border-white/10 bg-white/[0.02] relative overflow-hidden group">
          <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
          <h4 className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 mb-4">PREVISUALIZAÇÃO WHATSAPP</h4>
          <div className="bg-[#0b141a] rounded-2xl p-4 border border-white/10 shadow-2xl">
            <div className="flex gap-3">
              <div className="w-8 h-8 rounded-full bg-emerald-500/20 flex items-center justify-center shrink-0">
                <span className="text-xs text-emerald-400">👤</span>
              </div>
              <div className="bg-[#202c33] p-3 rounded-tr-xl rounded-b-xl max-w-[85%] text-[11px] text-foreground/90 leading-snug font-sans">
                Olá, João! Sofia aqui da Lumina Clinic. 🏥 Apenas passando para confirmar sua consulta de amanhã às 14h. Podemos confirmar sua presença?
              </div>
            </div>
          </div>
        </div>

      </div>

      {error && (
        <div className="lg:col-span-12">
          <p className="text-xs text-destructive font-sans font-medium">{error}</p>
        </div>
      )}

      {/* Action Bar */}
      <div className="flex items-center gap-4 pt-4 border-t border-white/5 lg:col-span-12 w-full">
        <button 
          onClick={handleSave} 
          disabled={isPending} 
          className="sofia-btn-gradient px-5 py-2.5 rounded-xl text-white font-bold text-xs shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center disabled:opacity-50"
        >
          {isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Save className="mr-1.5 h-3.5 w-3.5" />}
          Salvar Configurações
        </button>
        {isSuccess && <span className="text-xs text-emerald-400 font-sans font-semibold">Configurações salvas com sucesso!</span>}
      </div>
    </div>
  );
}

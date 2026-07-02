import { useEffect, useState } from "react";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Appointment, AppointmentStatus, useCreateAppointment, useUpdateAppointment, useServices,
} from "@/hooks/useCalendar";
import { useContacts } from "@/hooks/useInbox";
import { useTeamMembers } from "@/hooks/useTeam";
import { Loader2, CheckCircle2, UserCheck, XCircle, CalendarClock, Sparkles, Save } from "lucide-react";
import { cn } from "@/lib/utils";

interface AppointmentModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  appointment?: Appointment | null;
  defaultDate?: Date;
}

const STATUS_ACTIONS: { status: AppointmentStatus; label: string; icon: typeof CheckCircle2; cls: string }[] = [
  { status: "confirmed", label: "Confirmar", icon: CheckCircle2, cls: "text-emerald-400 border-emerald-500/20 bg-emerald-500/5 hover:bg-emerald-500/10" },
  { status: "completed", label: "Compareceu", icon: UserCheck, cls: "text-slate-400 border-white/10 bg-white/5 hover:bg-white/10" },
  { status: "no_show", label: "Não compareceu", icon: CalendarClock, cls: "text-amber-400 border-amber-500/20 bg-amber-500/5 hover:bg-amber-500/10" },
  { status: "cancelled", label: "Cancelar", icon: XCircle, cls: "text-destructive border-destructive/20 bg-destructive/5 hover:bg-destructive/10" },
];

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function defaultLocalInput(date?: Date): string {
  const d = date ? new Date(date) : new Date();
  d.setHours(9, 0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function AppointmentModal({ open, onOpenChange, appointment, defaultDate }: AppointmentModalProps) {
  const isEdit = !!appointment;
  const { data: contacts } = useContacts();
  const { data: services } = useServices();
  const { data: team } = useTeamMembers();
  const createAppt = useCreateAppointment();
  const updateAppt = useUpdateAppointment();

  const [contactId, setContactId] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [professionalId, setProfessionalId] = useState("");
  const [scheduledLocal, setScheduledLocal] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    if (appointment) {
      setContactId(appointment.contact_id);
      setServiceId(appointment.service_id || "");
      setProfessionalId(appointment.professional_id || "");
      setScheduledLocal(toLocalInput(appointment.scheduled_at));
      setNotes(appointment.notes || "");
    } else {
      setContactId("");
      setServiceId("");
      setProfessionalId("");
      setScheduledLocal(defaultLocalInput(defaultDate));
      setNotes("");
    }
  }, [open, appointment, defaultDate]);

  const isSaving = createAppt.isPending || updateAppt.isPending;

  const errMessage = (e: unknown): string => {
    const anyErr = e as { response?: { data?: { error?: { message?: string }; detail?: string }; status?: number } };
    if (anyErr?.response?.status === 409) return "Já existe um agendamento para este profissional nesse horário.";
    return anyErr?.response?.data?.error?.message || anyErr?.response?.data?.detail || "Erro ao salvar o agendamento.";
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!contactId) { setError("Selecione um paciente."); return; }
    if (!scheduledLocal) { setError("Informe a data e hora."); return; }

    const payload = {
      contact_id: contactId,
      service_id: serviceId || null,
      professional_id: professionalId || null,
      scheduled_at: new Date(scheduledLocal).toISOString(),
      notes: notes || null,
    };

    try {
      if (isEdit && appointment) {
        await updateAppt.mutateAsync({
          id: appointment.id,
          data: {
            service_id: payload.service_id,
            professional_id: payload.professional_id,
            scheduled_at: payload.scheduled_at,
            notes: payload.notes,
          },
        });
      } else {
        await createAppt.mutateAsync(payload);
      }
      onOpenChange(false);
    } catch (err) {
      setError(errMessage(err));
    }
  };

  const handleStatus = async (status: AppointmentStatus) => {
    if (!appointment) return;
    setError(null);
    let cancellation_reason: string | undefined;
    if (status === "cancelled") {
      const reason = window.prompt("Motivo do cancelamento:");
      if (reason === null) return; // user aborted
      cancellation_reason = reason || "Cancelado pela equipe";
    }
    try {
      await updateAppt.mutateAsync({ id: appointment.id, data: { status, cancellation_reason } });
      onOpenChange(false);
    } catch (err) {
      setError(errMessage(err));
    }
  };

  const attendingTeam = (team || []).filter((u) => u.is_active);

  const inputClass = "h-11 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px] bg-background/95 border-white/10 backdrop-blur-md rounded-[28px] p-6 shadow-2xl overflow-hidden animate-in fade-in zoom-in duration-300">
        <DialogHeader className="space-y-1">
          <div className="flex items-center gap-2 mb-1.5">
            <Sparkles className="text-primary h-4 w-4 animate-pulse" />
            <span className="font-mono text-[9px] uppercase tracking-widest text-primary font-semibold">Inteligência Sofia</span>
          </div>
          <DialogTitle className="font-heading text-xl font-bold text-foreground">
            {isEdit ? "Editar Agendamento" : "Novo Agendamento"}
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground/80 font-sans">
            {isEdit ? "Altere os dados ou atualize o status do agendamento." : "Preencha os dados abaixo para marcar uma nova consulta."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 pt-2">
          <div className="space-y-1.5">
            <Label htmlFor="contact" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80">Paciente</Label>
            <select
              id="contact"
              value={contactId}
              onChange={(e) => setContactId(e.target.value)}
              disabled={isEdit}
              className={`${inputClass} appearance-none bg-[url('data:image/svg+xml,%3Csvg_xmlns=%22http://www.w3.org/2000/svg%22_fill=%22none%22_viewBox=%220_0_24_24%22_stroke=%22%23cbc3d7%22%3E%3Cpath_stroke-linecap=%22round%22_stroke-linejoin=%22round%22_stroke-width=%222%22_d=%22M19_9l-7_7-7-7%22%3E%3C/path%3E%3C/svg%3E')] bg-no-repeat bg-[right_1rem_center] bg-[length:1.25rem]`}
            >
              <option value="" className="bg-background">Selecione um paciente…</option>
              {(contacts || []).map((c) => (
                <option key={c.id} value={c.id} className="bg-background">
                  {c.full_name}{c.phone ? ` · ${c.phone}` : ""}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="service" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80">Serviço</Label>
              <select
                id="service"
                value={serviceId}
                onChange={(e) => setServiceId(e.target.value)}
                className={`${inputClass} appearance-none bg-[url('data:image/svg+xml,%3Csvg_xmlns=%22http://www.w3.org/2000/svg%22_fill=%22none%22_viewBox=%220_0_24_24%22_stroke=%22%23cbc3d7%22%3E%3Cpath_stroke-linecap=%22round%22_stroke-linejoin=%22round%22_stroke-width=%222%22_d=%22M19_9l-7_7-7-7%22%3E%3C/path%3E%3C/svg%3E')] bg-no-repeat bg-[right_1rem_center] bg-[length:1.25rem]`}
              >
                <option value="" className="bg-background">Sem serviço</option>
                {(services || []).map((s) => (
                  <option key={s.id} value={s.id} className="bg-background">{s.name} ({s.duration_minutes}min)</option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="professional" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80">Profissional</Label>
              <select
                id="professional"
                value={professionalId}
                onChange={(e) => setProfessionalId(e.target.value)}
                className={`${inputClass} appearance-none bg-[url('data:image/svg+xml,%3Csvg_xmlns=%22http://www.w3.org/2000/svg%22_fill=%22none%22_viewBox=%220_0_24_24%22_stroke=%22%23cbc3d7%22%3E%3Cpath_stroke-linecap=%22round%22_stroke-linejoin=%22round%22_stroke-width=%222%22_d=%22M19_9l-7_7-7-7%22%3E%3C/path%3E%3C/svg%3E')] bg-no-repeat bg-[right_1rem_center] bg-[length:1.25rem]`}
              >
                <option value="" className="bg-background">Sem profissional</option>
                {attendingTeam.map((u) => (
                  <option key={u.id} value={u.id} className="bg-background">{u.full_name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="scheduled" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80">Data e hora</Label>
            <Input
              id="scheduled"
              type="datetime-local"
              value={scheduledLocal}
              onChange={(e) => setScheduledLocal(e.target.value)}
              className={inputClass}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="notes" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80">Observações</Label>
            <textarea
              id="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              className="flex w-full rounded-xl border border-white/10 bg-background/55 text-foreground px-4 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
              placeholder="Opcional"
            />
          </div>

          {isEdit && (
            <div className="space-y-1.5 pt-1">
              <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block mb-1">Status da consulta</span>
              <div className="flex flex-wrap gap-2">
                {STATUS_ACTIONS.map((a) => (
                  <Button
                    key={a.status}
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={isSaving || appointment?.status === a.status}
                    onClick={() => handleStatus(a.status)}
                    className={cn("h-8 rounded-lg px-2.5 text-xs font-semibold transition-all cursor-pointer", a.cls)}
                  >
                    <a.icon className="mr-1.5 h-3.5 w-3.5" />
                    {a.label}
                  </Button>
                ))}
              </div>
            </div>
          )}

          {error && <p className="text-sm text-destructive font-sans font-medium">{error}</p>}

          <DialogFooter className="pt-4 border-t border-white/10 flex flex-col-reverse sm:flex-row justify-end gap-3 mt-4">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="px-5 py-2.5 rounded-xl font-semibold text-muted-foreground hover:bg-white/5 hover:text-foreground text-xs transition-all cursor-pointer text-center"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={isSaving}
              className="sofia-btn-gradient px-5 py-2.5 rounded-xl text-white font-bold text-xs shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center"
            >
              {isSaving ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              {isEdit ? "Salvar Agendamento" : "Salvar Agendamento"}
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

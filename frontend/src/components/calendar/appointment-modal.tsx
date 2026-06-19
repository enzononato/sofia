"use client";

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
import { Loader2, CheckCircle2, UserCheck, XCircle, CalendarClock } from "lucide-react";

interface AppointmentModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  appointment?: Appointment | null;
  defaultDate?: Date;
}

const STATUS_ACTIONS: { status: AppointmentStatus; label: string; icon: typeof CheckCircle2; cls: string }[] = [
  { status: "confirmed", label: "Confirmar", icon: CheckCircle2, cls: "text-emerald-600 border-emerald-500/30 hover:bg-emerald-500/10" },
  { status: "completed", label: "Compareceu", icon: UserCheck, cls: "text-slate-600 border-slate-500/30 hover:bg-slate-500/10" },
  { status: "no_show", label: "Não compareceu", icon: CalendarClock, cls: "text-amber-600 border-amber-500/30 hover:bg-amber-500/10" },
  { status: "cancelled", label: "Cancelar", icon: XCircle, cls: "text-destructive border-destructive/30 hover:bg-destructive/10" },
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Editar Agendamento" : "Novo Agendamento"}</DialogTitle>
          <DialogDescription>
            {isEdit ? "Altere os dados ou atualize o status do agendamento." : "Agende um atendimento manualmente."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="contact">Paciente</Label>
            <select
              id="contact"
              value={contactId}
              onChange={(e) => setContactId(e.target.value)}
              disabled={isEdit}
              className="flex h-9 w-full rounded-lg border border-input bg-background px-3 text-sm disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <option value="">Selecione um paciente…</option>
              {(contacts || []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.full_name}{c.phone ? ` · ${c.phone}` : ""}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="service">Serviço</Label>
              <select
                id="service"
                value={serviceId}
                onChange={(e) => setServiceId(e.target.value)}
                className="flex h-9 w-full rounded-lg border border-input bg-background px-3 text-sm"
              >
                <option value="">Sem serviço</option>
                {(services || []).map((s) => (
                  <option key={s.id} value={s.id}>{s.name} ({s.duration_minutes}min)</option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="professional">Profissional</Label>
              <select
                id="professional"
                value={professionalId}
                onChange={(e) => setProfessionalId(e.target.value)}
                className="flex h-9 w-full rounded-lg border border-input bg-background px-3 text-sm"
              >
                <option value="">Sem profissional</option>
                {attendingTeam.map((u) => (
                  <option key={u.id} value={u.id}>{u.full_name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="scheduled">Data e hora</Label>
            <Input
              id="scheduled"
              type="datetime-local"
              value={scheduledLocal}
              onChange={(e) => setScheduledLocal(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="notes">Observações</Label>
            <textarea
              id="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              className="flex w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
              placeholder="Opcional"
            />
          </div>

          {isEdit && (
            <div className="flex flex-wrap gap-2 pt-1">
              {STATUS_ACTIONS.map((a) => (
                <Button
                  key={a.status}
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={isSaving || appointment?.status === a.status}
                  onClick={() => handleStatus(a.status)}
                  className={a.cls}
                >
                  <a.icon className="mr-1.5 h-3.5 w-3.5" />
                  {a.label}
                </Button>
              ))}
            </div>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}

          <DialogFooter className="pt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
            <Button type="submit" disabled={isSaving}>
              {isSaving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {isEdit ? "Salvar" : "Agendar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

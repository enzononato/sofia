"use client";

import { useEffect, useState } from "react";
import { useServices } from "@/hooks/useCalendar";
import {
  User,
  WorkHourBlock,
  useUserDetail,
  useSetUserServices,
  useSetUserWorkHours,
} from "@/hooks/useTeam";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Loader2, Plus, Trash2, Clock, Briefcase } from "lucide-react";

const WEEKDAYS: { id: number; label: string }[] = [
  { id: 1, label: "Segunda" },
  { id: 2, label: "Terça" },
  { id: 3, label: "Quarta" },
  { id: 4, label: "Quinta" },
  { id: 5, label: "Sexta" },
  { id: 6, label: "Sábado" },
  { id: 7, label: "Domingo" },
];

const toHHMM = (t: string) => (t ? t.slice(0, 5) : "");

interface Props {
  user: User | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ProfessionalConfigDialog({ user, open, onOpenChange }: Props) {
  const { data: detail, isLoading } = useUserDetail(open && user ? user.id : undefined);
  const { data: services } = useServices();
  const setServices = useSetUserServices();
  const setWorkHours = useSetUserWorkHours();

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [blocks, setBlocks] = useState<WorkHourBlock[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (detail) {
      setSelected(new Set(detail.service_ids));
      setBlocks(
        detail.work_hours.map((w) => ({
          weekday: w.weekday,
          start_time: toHHMM(w.start_time),
          end_time: toHHMM(w.end_time),
        }))
      );
      setError(null);
    }
  }, [detail]);

  const activeServices = (services ?? []).filter((s) => s.is_active);

  const toggleService = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const addBlock = (weekday: number) =>
    setBlocks((prev) => [...prev, { weekday, start_time: "08:00", end_time: "12:00" }]);

  const removeBlock = (globalIdx: number) =>
    setBlocks((prev) => prev.filter((_, i) => i !== globalIdx));

  const updateBlock = (globalIdx: number, field: "start_time" | "end_time", value: string) =>
    setBlocks((prev) => prev.map((b, i) => (i === globalIdx ? { ...b, [field]: value } : b)));

  const validate = (): string | null => {
    for (const b of blocks) {
      if (!b.start_time || !b.end_time) return "Preencha o horário de início e fim de todos os blocos.";
      if (b.start_time >= b.end_time) return "Há blocos com horário final menor ou igual ao inicial.";
    }
    // overlap per weekday
    for (const day of WEEKDAYS) {
      const ranges = blocks
        .filter((b) => b.weekday === day.id)
        .map((b) => [b.start_time, b.end_time] as [string, string])
        .sort((a, z) => a[0].localeCompare(z[0]));
      for (let i = 1; i < ranges.length; i++) {
        if (ranges[i][0] < ranges[i - 1][1]) {
          return `Blocos de horário sobrepostos em ${day.label}.`;
        }
      }
    }
    return null;
  };

  const handleSave = async () => {
    if (!user) return;
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    setSaving(true);
    try {
      await setServices.mutateAsync({ id: user.id, service_ids: Array.from(selected) });
      await setWorkHours.mutateAsync({ id: user.id, blocks });
      onOpenChange(false);
    } catch (e: any) {
      setError(
        e?.response?.data?.error?.message ??
          e?.response?.data?.detail ??
          "Erro ao salvar a configuração. Tente novamente."
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Atendimento de {user?.full_name}</DialogTitle>
          <DialogDescription>
            Defina quais serviços este profissional realiza e seus horários de trabalho. A Sofia
            usa isso para agendar pacientes com o profissional certo.
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex justify-center p-12">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="space-y-8 pt-2">
            {/* ── Services ─────────────────────────────────────────── */}
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <Briefcase className="h-4 w-4 text-muted-foreground" />
                <h3 className="text-sm font-semibold">Serviços que realiza</h3>
              </div>
              {activeServices.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Nenhum serviço ativo cadastrado. Cadastre serviços primeiro na aba Serviços.
                </p>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {activeServices.map((s) => (
                    <label
                      key={s.id}
                      className="flex items-center gap-2 rounded-lg border border-border/50 px-3 py-2 cursor-pointer hover:bg-muted/30 transition-colors"
                    >
                      <input
                        type="checkbox"
                        checked={selected.has(s.id)}
                        onChange={() => toggleService(s.id)}
                        className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                      />
                      <span className="text-sm truncate">
                        {s.name}{" "}
                        <span className="text-xs text-muted-foreground">({s.duration_minutes}min)</span>
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </section>

            {/* ── Work hours ───────────────────────────────────────── */}
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-muted-foreground" />
                <h3 className="text-sm font-semibold">Horários de trabalho</h3>
              </div>
              <p className="text-xs text-muted-foreground -mt-1">
                Adicione blocos por dia. O intervalo entre dois blocos (ex.: 08:00–12:00 e 13:00–18:00) é
                o almoço. Dias sem bloco = não atende. Sem nenhum horário definido, a Sofia usa o horário geral da clínica.
              </p>

              <div className="space-y-2">
                {WEEKDAYS.map((day) => {
                  const dayBlocks = blocks
                    .map((b, idx) => ({ b, idx }))
                    .filter((x) => x.b.weekday === day.id);
                  return (
                    <div
                      key={day.id}
                      className="flex flex-col sm:flex-row sm:items-start gap-2 rounded-lg border border-border/50 p-3"
                    >
                      <div className="w-24 shrink-0 text-sm font-medium pt-1.5">{day.label}</div>
                      <div className="flex-1 space-y-2">
                        {dayBlocks.length === 0 ? (
                          <span className="text-xs text-muted-foreground italic">Não atende</span>
                        ) : (
                          dayBlocks.map(({ b, idx }) => (
                            <div key={idx} className="flex items-center gap-2">
                              <input
                                type="time"
                                value={b.start_time}
                                onChange={(e) => updateBlock(idx, "start_time", e.target.value)}
                                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                              />
                              <span className="text-muted-foreground text-sm">até</span>
                              <input
                                type="time"
                                value={b.end_time}
                                onChange={(e) => updateBlock(idx, "end_time", e.target.value)}
                                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                              />
                              <button
                                type="button"
                                onClick={() => removeBlock(idx)}
                                className="text-muted-foreground hover:text-destructive p-1"
                                aria-label="Remover bloco"
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            </div>
                          ))
                        )}
                        <button
                          type="button"
                          onClick={() => addBlock(day.id)}
                          className="text-xs text-primary hover:underline flex items-center gap-1"
                        >
                          <Plus className="h-3 w-3" /> Adicionar bloco
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            {error && (
              <p className="text-sm text-destructive border border-destructive/40 bg-destructive/5 rounded-md p-2">
                {error}
              </p>
            )}
          </div>
        )}

        <DialogFooter className="pt-4">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button type="button" onClick={handleSave} disabled={saving || isLoading}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Salvar Atendimento
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

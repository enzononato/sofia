"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { formatDistanceToNowStrict } from "date-fns";
import { ptBR } from "date-fns/locale";
import { Patient, usePatients, useUpdatePatient } from "@/hooks/usePatients";
import { CrmStage } from "@/hooks/useCrm";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  Search,
  UserRound,
  Users,
  Bot,
  BotOff,
  MessageCircle,
  Loader2,
  Save,
  Flame,
} from "lucide-react";
import { cn } from "@/lib/utils";

// Same ids/labels/palette as the CRM Kanban board (components/crm/kanban-board.tsx)
// — kept in sync intentionally so a patient's stage reads identically everywhere.
const STAGES: { id: CrmStage; label: string; badge: string }[] = [
  { id: "new_lead", label: "Novo Lead", badge: "border-slate-500/20 bg-slate-500/10 text-slate-400" },
  { id: "cold_lead", label: "Lead Frio", badge: "border-sky-500/20 bg-sky-500/10 text-sky-400" },
  { id: "hot_lead", label: "Lead Quente", badge: "border-orange-500/20 bg-orange-500/10 text-orange-400" },
  { id: "scheduled", label: "Agendado", badge: "border-amber-500/20 bg-amber-500/10 text-amber-400" },
  { id: "attended", label: "Compareceu", badge: "border-emerald-500/20 bg-emerald-500/10 text-emerald-400" },
  { id: "post_care", label: "Pós-atendimento", badge: "border-violet-500/20 bg-violet-500/10 text-violet-400" },
  { id: "lost", label: "Perdido", badge: "border-rose-500/20 bg-rose-500/10 text-rose-400" },
];
const STAGE_BY_ID = Object.fromEntries(STAGES.map((s) => [s.id, s]));

function initialsOf(name: string) {
  return name.split(" ").map((n) => n[0]).filter(Boolean).join("").toUpperCase().slice(0, 2) || "?";
}

function lastContactLabel(lastInboundAt?: string | null) {
  if (!lastInboundAt) return "—";
  try {
    return formatDistanceToNowStrict(new Date(lastInboundAt), { addSuffix: true, locale: ptBR });
  } catch {
    return "—";
  }
}

const formSchema = z.object({
  full_name: z.string().min(2, "Nome muito curto").max(255, "Máximo de 255 caracteres"),
  email: z.string().email("E-mail inválido").optional().or(z.literal("")),
  phone: z.string().max(50, "Máximo de 50 caracteres").optional().or(z.literal("")),
  address: z.string().optional().or(z.literal("")),
});

type FormValues = z.infer<typeof formSchema>;

export default function PatientsPage() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [stageFilter, setStageFilter] = useState<CrmStage | "all">("all");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingPatient, setEditingPatient] = useState<Patient | null>(null);

  // Simple debounce — avoids firing a request on every keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput), 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const { data: patients, isLoading, isError } = usePatients({ search: search || undefined });
  const { mutateAsync: updatePatient, isPending: isSaving } = useUpdatePatient();

  const { register, handleSubmit, reset, formState: { errors } } = useForm<FormValues>({
    resolver: zodResolver(formSchema) as any,
    defaultValues: { full_name: "", email: "", phone: "", address: "" },
  });

  const openEditModal = (patient: Patient) => {
    setEditingPatient(patient);
    reset({
      full_name: patient.full_name,
      email: patient.email || "",
      phone: patient.phone || "",
      address: patient.address || "",
    });
    setIsModalOpen(true);
  };

  const onSubmit = async (data: FormValues) => {
    if (!editingPatient) return;
    try {
      await updatePatient({
        id: editingPatient.id,
        data: {
          full_name: data.full_name,
          email: data.email ? data.email : null,
          phone: data.phone ? data.phone : null,
          address: data.address ? data.address : null,
        },
      });
      setIsModalOpen(false);
    } catch (error) {
      console.error("Failed to update patient", error);
    }
  };

  // crm_stage has no backend filter on this endpoint — narrow client-side over
  // the already-fetched (search-narrowed) page, same as useCrmContacts does.
  const filteredPatients = (patients ?? []).filter(
    (p) => stageFilter === "all" || p.crm_stage === stageFilter
  );

  // ── Real, derived stats (no fabricated analytics) ──────────────────────────
  const total = patients?.length ?? 0;
  const pausedCount = patients?.filter((p) => p.ai_paused).length ?? 0;
  const hotLeadCount = patients?.filter((p) => p.crm_stage === "hot_lead").length ?? 0;

  return (
    <div className="flex flex-col h-full max-w-6xl mx-auto p-4 md:p-8">
      {/* ── Page Header ── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-8">
        <div>
          <h1 className="font-heading text-2xl md:text-3xl font-bold tracking-tight text-foreground">
            Pacientes
          </h1>
          <p className="text-muted-foreground mt-2 text-sm font-sans max-w-2xl">
            Consulte e edite os dados dos pacientes e leads da clínica, e acompanhe o estágio de cada um no funil de atendimento.
          </p>
        </div>
      </div>

      {/* ── Stat cards (real, derived data) ── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <div className="glass-card flex items-center gap-5 rounded-3xl p-6">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
            <Users className="h-6 w-6" />
          </div>
          <div>
            <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Total de Pacientes</p>
            <p className="font-heading text-xl font-bold text-foreground">{total}</p>
          </div>
        </div>

        <div className="glass-card flex items-center gap-5 rounded-3xl p-6">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-orange-500/10 text-orange-400">
            <Flame className="h-6 w-6" />
          </div>
          <div>
            <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Leads Quentes</p>
            <p className="font-heading text-xl font-bold text-foreground">{hotLeadCount}</p>
          </div>
        </div>

        <div className="glass-card flex items-center gap-5 rounded-3xl p-6">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-500/10 text-amber-400">
            <BotOff className="h-6 w-6" />
          </div>
          <div>
            <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Sofia Pausada</p>
            <p className="font-heading text-xl font-bold text-foreground">{pausedCount}</p>
          </div>
        </div>
      </div>

      {/* ── Search + Stage filter ── */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <div className="relative max-w-sm w-full">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar por nome ou telefone..."
            className="pl-10 h-10 bg-background/55 dark:bg-background/55 border-white/10 focus-visible:border-primary/50 focus-visible:ring-0 rounded-full placeholder:text-muted-foreground/60 text-sm"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
        </div>
        <div className="relative w-full sm:w-56">
          <select
            value={stageFilter}
            onChange={(e) => setStageFilter(e.target.value as CrmStage | "all")}
            className="h-10 w-full rounded-full border border-white/10 bg-background/55 px-4 text-sm text-foreground appearance-none cursor-pointer focus-visible:border-primary/50 focus-visible:outline-none focus-visible:ring-0"
          >
            <option value="all">Todos os estágios</option>
            {STAGES.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* ── Patients table ── */}
      {isLoading ? (
        <div className="glass-card rounded-[32px] p-6 space-y-4 animate-pulse">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="flex items-center gap-4">
              <div className="h-12 w-12 rounded-full bg-white/5" />
              <div className="flex-1 space-y-2">
                <div className="h-4 w-1/3 bg-white/5 rounded" />
                <div className="h-3 w-1/2 bg-white/5 rounded" />
              </div>
            </div>
          ))}
        </div>
      ) : isError ? (
        <div className="glass-card rounded-2xl border-destructive/20 bg-destructive/5 p-6">
          <h3 className="font-heading text-lg font-bold text-destructive">Erro ao carregar pacientes</h3>
          <p className="text-destructive/80 font-sans text-xs mt-1">Verifique sua conexão ou tente recarregar a página.</p>
        </div>
      ) : filteredPatients.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-12 text-center glass-card rounded-[32px]">
          <UserRound className="h-12 w-12 text-muted-foreground/40 mb-4" />
          <h3 className="font-heading text-lg font-semibold text-foreground">Nenhum paciente encontrado</h3>
          <p className="text-sm text-muted-foreground mt-1 mb-4 font-sans">
            {search || stageFilter !== "all" ? "Tente ajustar a busca ou o filtro de estágio." : "Ainda não há pacientes ou leads cadastrados."}
          </p>
        </div>
      ) : (
        <div className="glass-card rounded-[32px] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse min-w-[720px]">
              <thead>
                <tr className="border-b border-white/10 bg-white/[0.02]">
                  <th className="px-6 py-5 text-left font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Paciente</th>
                  <th className="px-4 py-5 text-left font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Estágio CRM</th>
                  <th className="px-4 py-5 text-left font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Último contato</th>
                  <th className="px-4 py-5 text-left font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Sofia</th>
                  <th className="px-6 py-5 text-right font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Ações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06]">
                {filteredPatients.map((patient) => {
                  const stage = STAGE_BY_ID[patient.crm_stage] as (typeof STAGES)[number] | undefined;
                  return (
                    <tr
                      key={patient.id}
                      onClick={() => openEditModal(patient)}
                      className="group cursor-pointer transition-colors hover:bg-white/[0.03]"
                    >
                      {/* Patient */}
                      <td className="px-6 py-5">
                        <div className="flex items-center gap-4">
                          <Avatar className="h-12 w-12 border border-white/10 flex-shrink-0" size="lg">
                            <AvatarImage src={patient.profile_picture_url || ""} />
                            <AvatarFallback className="bg-gradient-to-br from-primary/25 to-secondary/25 text-primary font-heading font-bold">
                              {initialsOf(patient.full_name)}
                            </AvatarFallback>
                          </Avatar>
                          <div className="min-w-0">
                            <p className="font-heading text-sm font-semibold text-foreground truncate">{patient.full_name}</p>
                            <p className="text-xs text-muted-foreground font-sans mt-0.5">
                              {patient.phone || "Sem telefone"}
                            </p>
                          </div>
                        </div>
                      </td>

                      {/* CRM stage badge */}
                      <td className="px-4 py-5">
                        <span
                          className={cn(
                            "inline-flex w-fit items-center rounded-full border px-2.5 py-1 font-mono text-[9px] uppercase tracking-wider",
                            stage?.badge ?? "border-white/10 bg-white/5 text-muted-foreground"
                          )}
                        >
                          {stage?.label ?? patient.crm_stage}
                        </span>
                      </td>

                      {/* Last contact (relative time) */}
                      <td className="px-4 py-5">
                        <span className="text-sm text-foreground font-sans whitespace-nowrap">
                          {lastContactLabel(patient.last_inbound_at)}
                        </span>
                      </td>

                      {/* Sofia status */}
                      <td className="px-4 py-5">
                        {patient.ai_paused ? (
                          <span className="inline-flex w-fit items-center gap-1.5 rounded-full border border-amber-500/20 bg-amber-500/10 px-2.5 py-1 font-mono text-[9px] uppercase tracking-wider text-amber-400">
                            <BotOff className="h-3 w-3" /> Pausada
                          </span>
                        ) : (
                          <span className="inline-flex w-fit items-center gap-1.5 rounded-full border border-primary/20 bg-primary/5 px-2.5 py-1 font-mono text-[9px] uppercase tracking-wider text-primary/80">
                            <Bot className="h-3 w-3" /> Ativa
                          </span>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="px-6 py-5 text-right">
                        <Link
                          href={`/dashboard/inbox?contact=${patient.id}`}
                          onClick={(e) => e.stopPropagation()}
                          title="Abrir no Inbox"
                          aria-label={`Abrir conversa com ${patient.full_name} no Inbox`}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-primary transition-colors hover:bg-primary/10 hover:text-[#c4b5fd] cursor-pointer"
                        >
                          <MessageCircle className="h-4 w-4" />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Edit Dialog */}
      <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
        <DialogContent className="sm:max-w-[425px] bg-background/95 border-white/10 backdrop-blur-md rounded-[28px] p-6 shadow-2xl overflow-hidden animate-in fade-in zoom-in duration-300">
          <DialogHeader>
            <DialogTitle className="font-heading text-xl font-bold text-foreground">
              Editar Paciente
            </DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground/80 font-sans mt-1">
              Atualize os dados de contato do paciente. Essas informações também são usadas pela Sofia durante o atendimento.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 pt-4">
            <div className="space-y-1.5">
              <Label htmlFor="full_name" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Nome Completo *</Label>
              <Input id="full_name" {...register("full_name")} placeholder="Ex: Maria da Silva" className="h-11 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
              {errors.full_name && <p className="text-xs text-destructive font-sans font-medium">{errors.full_name.message as string}</p>}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="email" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">E-mail</Label>
              <Input id="email" type="email" {...register("email")} placeholder="paciente@email.com" className="h-11 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
              {errors.email && <p className="text-xs text-destructive font-sans font-medium">{errors.email.message as string}</p>}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="phone" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Telefone</Label>
              <Input id="phone" {...register("phone")} placeholder="(11) 91234-5678" className="h-11 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
              {errors.phone && <p className="text-xs text-destructive font-sans font-medium">{errors.phone.message as string}</p>}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="address" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Endereço</Label>
              <Input id="address" {...register("address")} placeholder="Rua, número, bairro, cidade" className="h-11 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
              {errors.address && <p className="text-xs text-destructive font-sans font-medium">{errors.address.message as string}</p>}
            </div>

            <DialogFooter className="pt-4 border-t border-white/10 flex flex-col-reverse sm:flex-row justify-end gap-3 mt-4">
              <button type="button" onClick={() => setIsModalOpen(false)} className="px-5 py-2.5 rounded-xl font-semibold text-muted-foreground hover:bg-white/5 hover:text-foreground text-xs transition-all cursor-pointer text-center">
                Cancelar
              </button>
              <button type="submit" disabled={isSaving} className="sofia-btn-gradient px-5 py-2.5 rounded-xl text-white font-bold text-xs shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center">
                {isSaving ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="mr-1.5 h-3.5 w-3.5" />
                )}
                Salvar Alterações
              </button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

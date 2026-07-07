"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Service, useServices, useCreateService, useUpdateService } from "@/hooks/useCalendar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import {
  Clock,
  DollarSign,
  Plus,
  PlusCircle,
  Settings2,
  Loader2,
  Search,
  Pencil,
  Stethoscope,
  Timer,
  Receipt,
} from "lucide-react";
import { cn } from "@/lib/utils";

const formSchema = z.object({
  name: z.string().min(1, "Nome é obrigatório").max(100, "Máximo de 100 caracteres"),
  description: z.string().optional(),
  duration_minutes: z.coerce.number().min(5, "Mínimo de 5 minutos").max(480, "Máximo de 8 horas"),
  price: z.coerce.number().min(0, "O preço não pode ser negativo").optional().or(z.literal("")),
});

type FormValues = z.infer<typeof formSchema>;

const money = (v: number) =>
  v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function ServicesPage() {
  const { data: services, isLoading, isError } = useServices();
  const { mutateAsync: createService, isPending: isCreating } = useCreateService();
  const { mutateAsync: updateService, isPending: isUpdating } = useUpdateService();

  const [search, setSearch] = useState("");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingService, setEditingService] = useState<Service | null>(null);

  const { register, handleSubmit, reset, formState: { errors } } = useForm<FormValues>({
    resolver: zodResolver(formSchema) as any,
    defaultValues: {
      name: "",
      description: "",
      duration_minutes: 30,
      price: undefined,
    },
  });

  const openNewModal = () => {
    setEditingService(null);
    reset({ name: "", description: "", duration_minutes: 30, price: undefined });
    setIsModalOpen(true);
  };

  const openEditModal = (service: Service) => {
    setEditingService(service);
    reset({
      name: service.name,
      description: service.description || "",
      duration_minutes: service.duration_minutes,
      price: service.price ?? undefined,
    });
    setIsModalOpen(true);
  };

  const onSubmit = async (data: FormValues) => {
    try {
      const payload = {
        name: data.name,
        description: data.description || null,
        duration_minutes: data.duration_minutes,
        price: data.price !== "" && data.price !== undefined ? Number(data.price) : null,
      };

      if (editingService) {
        await updateService({ id: editingService.id, data: payload });
      } else {
        await createService(payload);
      }
      setIsModalOpen(false);
    } catch (error) {
      console.error("Failed to save service", error);
    }
  };

  const handleToggleActive = async (service: Service, checked: boolean) => {
    if (!checked) {
      const confirmed = window.confirm(
        "Atenção: Desativar este serviço impedirá novos agendamentos. Agendamentos futuros já marcados poderão ser afetados. Deseja continuar?"
      );
      if (!confirmed) return;
    }

    try {
      await updateService({ id: service.id, data: { is_active: checked } });
    } catch (error) {
      console.error("Failed to toggle service status", error);
      alert("Erro ao alterar o status do serviço.");
    }
  };

  const filteredServices = services?.filter(s =>
    s.name.toLowerCase().includes(search.toLowerCase()) ||
    (s.description && s.description.toLowerCase().includes(search.toLowerCase()))
  ) || [];

  // ── Real, derived KPIs (no fabricated analytics) ──────────────────────────
  const activeCount = services?.filter(s => s.is_active).length ?? 0;
  const avgDuration = services && services.length
    ? Math.round(services.reduce((sum, s) => sum + s.duration_minutes, 0) / services.length)
    : 0;
  const pricedServices = (services ?? []).filter(s => s.price != null && Number(s.price) > 0).map(s => Number(s.price));
  const avgPrice = pricedServices.length
    ? pricedServices.reduce((a, b) => a + b, 0) / pricedServices.length
    : null;

  return (
    <div className="flex flex-col h-full max-w-6xl mx-auto p-4 md:p-8">
      {/* ── Page Header ── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-8">
        <div>
          <h1 className="font-heading text-2xl md:text-3xl font-bold tracking-tight text-foreground">
            Gestão de Serviços
          </h1>
          <p className="text-muted-foreground mt-2 text-sm font-sans max-w-2xl">
            Configure seu catálogo de procedimentos, defina preços e tempos de execução para otimizar sua agenda.
          </p>
        </div>
        <button
          onClick={openNewModal}
          className="sofia-btn-gradient shrink-0 flex items-center gap-2 rounded-2xl px-6 py-4 font-heading text-base font-bold text-white shadow-xl shadow-primary/20 cursor-pointer"
        >
          <PlusCircle className="h-5 w-5" />
          Novo Serviço
        </button>
      </div>

      {/* ── Stat cards (real, derived data) ── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <div className="glass-card flex items-center gap-5 rounded-3xl p-6">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
            <Stethoscope className="h-6 w-6" />
          </div>
          <div>
            <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Total de Serviços</p>
            <p className="font-heading text-xl font-bold text-foreground">{activeCount} Ativos</p>
          </div>
        </div>

        <div className="glass-card flex items-center gap-5 rounded-3xl p-6">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#4cd7f6]/10 text-[#4cd7f6]">
            <Timer className="h-6 w-6" />
          </div>
          <div>
            <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Tempo Médio</p>
            <p className="font-heading text-xl font-bold text-foreground">{avgDuration} min</p>
          </div>
        </div>

        <div className="glass-card flex items-center gap-5 rounded-3xl p-6">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-secondary/10 text-secondary">
            <Receipt className="h-6 w-6" />
          </div>
          <div>
            <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Ticket Médio</p>
            <p className="font-heading text-xl font-bold text-foreground">
              {avgPrice != null ? `R$ ${money(avgPrice)}` : "—"}
            </p>
          </div>
        </div>
      </div>

      {/* ── Search ── */}
      <div className="relative mb-6 max-w-sm">
        <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Buscar serviços..."
          className="pl-10 h-10 bg-background/55 dark:bg-background/55 border-white/10 focus-visible:border-primary/50 focus-visible:ring-0 rounded-full placeholder:text-muted-foreground/60 text-sm"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* ── Service table ── */}
      {isLoading ? (
        <div className="glass-card rounded-[32px] p-6 space-y-4 animate-pulse">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="flex items-center gap-4">
              <div className="h-12 w-12 rounded-xl bg-white/5" />
              <div className="flex-1 space-y-2">
                <div className="h-4 w-1/3 bg-white/5 rounded" />
                <div className="h-3 w-1/2 bg-white/5 rounded" />
              </div>
            </div>
          ))}
        </div>
      ) : isError ? (
        <div className="glass-card rounded-2xl border-destructive/20 bg-destructive/5 p-6">
          <h3 className="font-heading text-lg font-bold text-destructive">Erro ao carregar serviços</h3>
          <p className="text-destructive/80 font-sans text-xs mt-1">Verifique sua conexão ou tente recarregar a página.</p>
        </div>
      ) : filteredServices.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-12 text-center glass-card rounded-[32px]">
          <Settings2 className="h-12 w-12 text-muted-foreground/40 mb-4" />
          <h3 className="font-heading text-lg font-semibold text-foreground">Nenhum serviço encontrado</h3>
          <p className="text-sm text-muted-foreground mt-1 mb-4 font-sans">
            {search ? "Tente usar outros termos na busca." : "Você ainda não cadastrou nenhum serviço."}
          </p>
          {!search && (
            <button onClick={openNewModal} className="sofia-btn-gradient rounded-xl px-5 py-2.5 text-xs font-bold text-white cursor-pointer">
              Cadastrar Primeiro Serviço
            </button>
          )}
        </div>
      ) : (
        <div className="glass-card rounded-[32px] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse min-w-[640px]">
              <thead>
                <tr className="border-b border-white/10 bg-white/[0.02]">
                  <th className="px-6 py-5 text-left font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Serviço</th>
                  <th className="px-4 py-5 text-left font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Duração</th>
                  <th className="px-4 py-5 text-left font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Preço</th>
                  <th className="px-4 py-5 text-left font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Status</th>
                  <th className="px-6 py-5 text-right font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Ações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06]">
                {filteredServices.map((service) => (
                  <tr
                    key={service.id}
                    onClick={() => openEditModal(service)}
                    className={cn(
                      "group cursor-pointer transition-colors hover:bg-white/[0.03]",
                      !service.is_active && "opacity-50"
                    )}
                  >
                    {/* Service (avatar with initial — no image field exists on the model) */}
                    <td className="px-6 py-5">
                      <div className="flex items-center gap-4">
                        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary/25 to-secondary/25 border border-white/10 font-heading text-lg font-bold text-primary">
                          {service.name.trim().charAt(0).toUpperCase() || "S"}
                        </div>
                        <div className="min-w-0">
                          <p className="font-heading text-sm font-semibold text-foreground truncate">{service.name}</p>
                          {service.description ? (
                            <p className="text-xs text-muted-foreground line-clamp-1 font-sans mt-0.5 max-w-[280px]">
                              {service.description}
                            </p>
                          ) : (
                            <p className="text-xs text-muted-foreground/40 italic font-sans mt-0.5">Sem descrição</p>
                          )}
                        </div>
                      </div>
                    </td>

                    {/* Duration */}
                    <td className="px-4 py-5">
                      <div className="flex items-center gap-2 text-foreground">
                        <Clock className="h-4 w-4 text-primary/80" />
                        <span className="text-sm font-sans whitespace-nowrap">{service.duration_minutes} min</span>
                      </div>
                    </td>

                    {/* Price — treat 0/unset alike: "assessed in consultation", never "R$ 0,00" */}
                    <td className="px-4 py-5">
                      {service.price != null && Number(service.price) > 0 ? (
                        <div className="flex flex-col items-start gap-1.5">
                          <div className="flex items-center gap-2 text-foreground">
                            <DollarSign className="h-4 w-4 text-secondary/80" />
                            <span className="text-sm font-sans whitespace-nowrap">R$ {money(Number(service.price))}</span>
                          </div>
                          <span
                            title="Este valor corresponde a uma única consulta/sessão, não a um pacote fechado."
                            className="inline-flex w-fit items-center rounded-full border border-white/10 bg-white/5 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider text-muted-foreground cursor-help"
                          >
                            Por consulta
                          </span>
                        </div>
                      ) : (
                        <span
                          title="Este serviço não tem valor fixo tabelado — o preço é avaliado e informado durante a consulta presencial."
                          className="inline-flex w-fit items-center rounded-full border border-amber-500/20 bg-amber-500/5 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider text-amber-400/90 cursor-help"
                        >
                          Valor na consulta
                        </span>
                      )}
                    </td>

                    {/* Status toggle */}
                    <td className="px-4 py-5">
                      <div className="cursor-pointer w-fit" onClick={(e) => e.stopPropagation()}>
                        <Switch
                          checked={service.is_active}
                          onCheckedChange={(checked) => handleToggleActive(service, checked)}
                          className="cursor-pointer"
                        />
                      </div>
                    </td>

                    {/* Actions */}
                    <td className="px-6 py-5 text-right">
                      <button
                        onClick={(e) => { e.stopPropagation(); openEditModal(service); }}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-primary transition-colors hover:bg-primary/10 hover:text-[#c4b5fd] cursor-pointer"
                        aria-label={`Editar ${service.name}`}
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Inline Create/Edit Dialog */}
      <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
        <DialogContent className="sm:max-w-[425px] bg-background/95 border-white/10 backdrop-blur-md rounded-[28px] p-6 shadow-2xl overflow-hidden animate-in fade-in zoom-in duration-300">
          <DialogHeader>
            <DialogTitle className="font-heading text-xl font-bold text-foreground">
              {editingService ? "Editar Serviço" : "Novo Serviço"}
            </DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground/80 font-sans mt-1">
              Preencha os detalhes do procedimento. Esses dados são lidos pela Sofia para informar e agendar os pacientes.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 pt-4">
            <div className="space-y-1.5">
              <Label htmlFor="name" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Nome do Serviço *</Label>
              <Input id="name" {...register("name")} placeholder="Ex: Limpeza Dental" className="h-11 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
              {errors.name && <p className="text-xs text-destructive font-sans font-medium">{errors.name.message as string}</p>}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="description" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Descrição</Label>
              <Textarea
                id="description"
                {...register("description")}
                placeholder="Ex: Remoção de tártaro e polimento..."
                className="rounded-xl border border-white/10 bg-background/55 text-foreground p-3 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 h-20 resize-none w-full"
              />
              {errors.description && <p className="text-xs text-destructive font-sans font-medium">{errors.description.message as string}</p>}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label htmlFor="duration_minutes" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Duração (min) *</Label>
                <div className="relative">
                  <Clock className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
                  <Input id="duration_minutes" type="number" {...register("duration_minutes")} className="h-11 rounded-xl border-white/10 bg-background/55 text-foreground pl-10 pr-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
                </div>
                {errors.duration_minutes && <p className="text-xs text-destructive font-sans font-medium">{errors.duration_minutes.message as string}</p>}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="price" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Preço (R$) - Opcional</Label>
                <div className="relative">
                  <DollarSign className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
                  <Input id="price" type="number" step="0.01" {...register("price")} className="h-11 rounded-xl border-white/10 bg-background/55 text-foreground pl-10 pr-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" placeholder="0.00" />
                </div>
                {errors.price && <p className="text-xs text-destructive font-sans font-medium">{errors.price.message as string}</p>}
              </div>
            </div>

            <DialogFooter className="pt-4 border-t border-white/10 flex flex-col-reverse sm:flex-row justify-end gap-3 mt-4">
              <button type="button" onClick={() => setIsModalOpen(false)} className="px-5 py-2.5 rounded-xl font-semibold text-muted-foreground hover:bg-white/5 hover:text-foreground text-xs transition-all cursor-pointer text-center">
                Cancelar
              </button>
              <button type="submit" disabled={isCreating || isUpdating} className="sofia-btn-gradient px-5 py-2.5 rounded-xl text-white font-bold text-xs shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center">
                {(isCreating || isUpdating) ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Plus className="mr-1.5 h-3.5 w-3.5" />
                )}
                Salvar Serviço
              </button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

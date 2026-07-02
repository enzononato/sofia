"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Service, useServices, useCreateService, useUpdateService } from "@/hooks/useCalendar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Clock, DollarSign, Plus, Settings2, Loader2, Search, FileText } from "lucide-react";
import { cn } from "@/lib/utils";

const formSchema = z.object({
  name: z.string().min(1, "Nome é obrigatório").max(100, "Máximo de 100 caracteres"),
  description: z.string().optional(),
  duration_minutes: z.coerce.number().min(5, "Mínimo de 5 minutos").max(480, "Máximo de 8 horas"),
  price: z.coerce.number().min(0, "O preço não pode ser negativo").optional().or(z.literal("")),
});

type FormValues = z.infer<typeof formSchema>;

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

  return (
    <div className="flex flex-col h-full max-w-6xl mx-auto p-4 md:p-8 bg-background/5">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="font-heading text-2xl font-bold tracking-tight text-foreground">Serviços e Procedimentos</h1>
          <p className="text-muted-foreground mt-1 text-sm font-sans">
            Gerencie os serviços oferecidos. A Sofia usará isso para sugerir e agendar os pacientes.
          </p>
        </div>
        <Button onClick={openNewModal} className="shrink-0 bg-primary text-primary-foreground hover:brightness-110 font-semibold cursor-pointer text-xs h-9 shadow-md shadow-primary/20 rounded-full px-4">
          <Plus className="mr-1.5 h-4 w-4" /> Novo Serviço
        </Button>
      </div>

      {/* Search Filter */}
      <div className="flex items-center space-x-2 mb-6">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar serviços..."
            className="pl-10 h-10 bg-background/55 border-white/10 focus-visible:border-primary/50 focus-visible:ring-0 rounded-xl placeholder:text-muted-foreground/60 text-sm"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="animate-pulse border-white/5 bg-white/5">
              <CardHeader className="h-24 bg-white/5 rounded-t-xl" />
              <CardContent className="py-4 space-y-3">
                <div className="h-4 w-1/2 bg-white/5 rounded" />
                <div className="h-4 w-1/3 bg-white/5 rounded" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : isError ? (
        <Card className="border-destructive/20 bg-destructive/5 text-destructive rounded-2xl">
          <CardHeader>
            <CardTitle className="font-heading text-lg font-bold text-destructive">Erro ao carregar serviços</CardTitle>
            <CardDescription className="text-destructive/80 font-sans text-xs">Verifique sua conexão ou tente recarregar a página.</CardDescription>
          </CardHeader>
        </Card>
      ) : filteredServices.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-12 text-center border border-dashed border-white/10 rounded-2xl bg-white/5 backdrop-blur-sm">
          <Settings2 className="h-12 w-12 text-muted-foreground/40 mb-4 animate-spin duration-3000" />
          <h3 className="font-heading text-lg font-semibold text-foreground">Nenhum serviço encontrado</h3>
          <p className="text-sm text-muted-foreground mt-1 mb-4 font-sans">
            {search ? "Tente usar outros termos na busca." : "Você ainda não cadastrou nenhum serviço."}
          </p>
          {!search && (
            <Button onClick={openNewModal} variant="outline" className="border-white/10 hover:bg-white/5 text-xs font-semibold cursor-pointer">
              Cadastrar Primeiro Serviço
            </Button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredServices.map((service) => (
            <Card 
              key={service.id} 
              className={cn(
                "flex flex-col transition-all hover:shadow-xl hover:border-primary/30 border border-white/10 bg-background/45 backdrop-blur-md rounded-2xl cursor-pointer relative overflow-hidden",
                !service.is_active && "opacity-60 grayscale-[0.2]"
              )}
              onClick={() => openEditModal(service)}
            >
              <CardHeader className="pb-3">
                <div className="flex justify-between items-start gap-2">
                  <CardTitle className="font-heading text-base font-bold text-foreground line-clamp-2 leading-tight">
                    {service.name}
                  </CardTitle>
                  <div className="shrink-0 cursor-pointer" onClick={e => e.stopPropagation()}>
                    <Switch
                      checked={service.is_active}
                      onCheckedChange={(checked) => handleToggleActive(service, checked)}
                      className="cursor-pointer"
                    />
                  </div>
                </div>
                {!service.is_active && (
                  <Badge variant="secondary" className="w-fit text-[9px] font-mono uppercase tracking-wider mt-1 bg-destructive/10 text-destructive border border-destructive/20 rounded-md">
                    Inativo
                  </Badge>
                )}
              </CardHeader>
              
              <CardContent className="flex-1 pb-4 flex flex-col justify-between">
                {service.description ? (
                  <p className="text-xs text-muted-foreground line-clamp-2 mb-4 font-sans leading-relaxed">
                    {service.description}
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground/40 italic mb-4 font-sans">
                    Sem descrição
                  </p>
                )}
                
                <div className="flex items-center gap-4 text-xs font-semibold mt-auto pt-2 border-t border-white/5">
                  <div className="flex items-center gap-1.5 text-foreground/80">
                    <Clock className="h-4 w-4 text-muted-foreground/60" />
                    {service.duration_minutes} min
                  </div>
                  {service.price != null && (
                    <div className="flex items-center gap-1.5 text-emerald-400 font-mono">
                      <DollarSign className="h-3.5 w-3.5 text-emerald-500" />
                      {Number(service.price).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
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

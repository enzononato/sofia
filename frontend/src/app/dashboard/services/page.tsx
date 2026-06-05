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
    <div className="flex flex-col h-full max-w-6xl mx-auto p-4 md:p-8">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Serviços e Procedimentos</h1>
          <p className="text-muted-foreground mt-1">
            Gerencie os serviços oferecidos. A Sofia usará isso para sugerir e agendar os pacientes.
          </p>
        </div>
        <Button onClick={openNewModal} className="shrink-0">
          <Plus className="mr-2 h-4 w-4" /> Novo Serviço
        </Button>
      </div>

      <div className="flex items-center space-x-2 mb-6">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar serviços..."
            className="pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="animate-pulse">
              <CardHeader className="h-24 bg-muted/30" />
              <CardContent className="py-4 space-y-3">
                <div className="h-4 w-1/2 bg-muted rounded" />
                <div className="h-4 w-1/3 bg-muted rounded" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : isError ? (
        <Card className="border-destructive/50 bg-destructive/5">
          <CardHeader>
            <CardTitle className="text-destructive">Erro ao carregar serviços</CardTitle>
            <CardDescription>Verifique sua conexão ou tente recarregar a página.</CardDescription>
          </CardHeader>
        </Card>
      ) : filteredServices.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-12 text-center border border-dashed rounded-xl bg-card/50">
          <Settings2 className="h-12 w-12 text-muted-foreground/50 mb-4" />
          <h3 className="text-lg font-medium">Nenhum serviço encontrado</h3>
          <p className="text-sm text-muted-foreground mt-1 mb-4">
            {search ? "Tente usar outros termos na busca." : "Você ainda não cadastrou nenhum serviço."}
          </p>
          {!search && (
            <Button onClick={openNewModal} variant="outline">
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
                "flex flex-col transition-all hover:shadow-md cursor-pointer hover:border-primary/30",
                !service.is_active && "opacity-75 grayscale-[0.2]"
              )}
              onClick={() => openEditModal(service)}
            >
              <CardHeader className="pb-3">
                <div className="flex justify-between items-start gap-2">
                  <CardTitle className="text-lg font-semibold line-clamp-2 leading-tight">
                    {service.name}
                  </CardTitle>
                  <div className="shrink-0" onClick={e => e.stopPropagation()}>
                    <Switch
                      checked={service.is_active}
                      onCheckedChange={(checked) => handleToggleActive(service, checked)}
                    />
                  </div>
                </div>
                {!service.is_active && (
                  <Badge variant="secondary" className="w-fit text-[10px] mt-1 bg-destructive/10 text-destructive">
                    Inativo
                  </Badge>
                )}
              </CardHeader>
              
              <CardContent className="flex-1 pb-4">
                {service.description ? (
                  <p className="text-sm text-muted-foreground line-clamp-2 mb-4">
                    {service.description}
                  </p>
                ) : (
                  <p className="text-sm text-muted-foreground/50 italic mb-4">
                    Sem descrição
                  </p>
                )}
                
                <div className="flex items-center gap-4 text-sm font-medium">
                  <div className="flex items-center gap-1.5 text-foreground/80">
                    <Clock className="h-4 w-4 text-muted-foreground" />
                    {service.duration_minutes} min
                  </div>
                  {service.price != null && (
                    <div className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400">
                      <DollarSign className="h-4 w-4" />
                      {Number(service.price).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{editingService ? "Editar Serviço" : "Novo Serviço"}</DialogTitle>
            <DialogDescription>
              Preencha os detalhes do procedimento. Esses dados são lidos pela Sofia para informar e agendar os pacientes.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 pt-4">
            <div className="space-y-2">
              <Label htmlFor="name">Nome do Serviço *</Label>
              <Input id="name" {...register("name")} placeholder="Ex: Limpeza Dental" />
              {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
            </div>

            <div className="space-y-2">
              <Label htmlFor="description">Descrição</Label>
              <Textarea 
                id="description" 
                {...register("description")} 
                placeholder="Ex: Remoção de tártaro e polimento..."
                className="h-20 resize-none"
              />
              {errors.description && <p className="text-sm text-destructive">{errors.description.message}</p>}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="duration_minutes">Duração (min) *</Label>
                <div className="relative">
                  <Clock className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                  <Input id="duration_minutes" type="number" {...register("duration_minutes")} className="pl-9" />
                </div>
                {errors.duration_minutes && <p className="text-xs text-destructive">{errors.duration_minutes.message}</p>}
              </div>

              <div className="space-y-2">
                <Label htmlFor="price">Preço (R$) - Opcional</Label>
                <div className="relative">
                  <DollarSign className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
                  <Input id="price" type="number" step="0.01" {...register("price")} className="pl-9" placeholder="0.00" />
                </div>
                {errors.price && <p className="text-xs text-destructive">{errors.price.message}</p>}
              </div>
            </div>

            <DialogFooter className="pt-4">
              <Button type="button" variant="outline" onClick={() => setIsModalOpen(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={isCreating || isUpdating}>
                {(isCreating || isUpdating) && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Salvar Serviço
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

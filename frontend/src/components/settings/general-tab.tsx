"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { TenantProfile, useUpdateTenant } from "@/hooks/useSettings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Building2, Mail, Phone, MapPin, Save, Loader2 } from "lucide-react";

const formSchema = z.object({
  name: z.string().min(2, "Nome deve ter no mínimo 2 caracteres"),
  email: z.string().email("E-mail inválido"),
  phone: z.string().optional(),
  address: z.string().optional(),
});

type FormValues = z.infer<typeof formSchema>;

export function GeneralTab({ tenant }: { tenant: TenantProfile }) {
  const { mutateAsync: updateTenant, isPending } = useUpdateTenant();
  const [isSuccess, setIsSuccess] = useState(false);

  const { register, handleSubmit, formState: { errors } } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      name: tenant.name,
      email: tenant.email,
      phone: tenant.phone || "",
      address: tenant.address || "",
    },
  });

  const onSubmit = async (data: FormValues) => {
    try {
      setIsSuccess(false);
      await updateTenant({
        name: data.name,
        email: data.email,
        phone: data.phone || null,
        address: data.address || null,
      });
      setIsSuccess(true);
      setTimeout(() => setIsSuccess(false), 3000);
    } catch (error) {
      console.error("Failed to update tenant", error);
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-6 max-w-2xl">
      <div>
        <h3 className="text-lg font-medium">Perfil da Clínica</h3>
        <p className="text-sm text-muted-foreground mt-1">
          Estas são as informações básicas da sua clínica.
        </p>
      </div>

      <div className="grid gap-6">
        <div className="grid gap-3">
          <Label htmlFor="name">Nome da Clínica</Label>
          <div className="relative">
            <Building2 className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
            <Input id="name" {...register("name")} className="pl-9" />
          </div>
          {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
        </div>

        <div className="grid gap-3">
          <Label htmlFor="email">E-mail de Contato</Label>
          <div className="relative">
            <Mail className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
            <Input id="email" type="email" {...register("email")} className="pl-9" />
          </div>
          {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
        </div>

        <div className="grid gap-3">
          <Label htmlFor="phone">Telefone / WhatsApp Principal</Label>
          <div className="relative">
            <Phone className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
            <Input id="phone" {...register("phone")} className="pl-9" placeholder="(11) 99999-9999" />
          </div>
          {errors.phone && <p className="text-sm text-destructive">{errors.phone.message}</p>}
        </div>

        <div className="grid gap-3">
          <Label htmlFor="address">Endereço Físico</Label>
          <div className="relative">
            <MapPin className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
            <Input id="address" {...register("address")} className="pl-9" placeholder="Rua Exemplo, 123" />
          </div>
          {errors.address && <p className="text-sm text-destructive">{errors.address.message}</p>}
        </div>
      </div>

      <div className="flex items-center gap-4 pt-4">
        <Button type="submit" disabled={isPending}>
          {isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          Salvar Alterações
        </Button>
        {isSuccess && <span className="text-sm text-emerald-500 font-medium">Salvo com sucesso!</span>}
      </div>
    </form>
  );
}

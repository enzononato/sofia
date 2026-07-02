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
        <h3 className="font-heading text-lg font-bold text-foreground">Perfil da Clínica</h3>
        <p className="text-xs text-muted-foreground/80 font-sans mt-0.5">
          Estas são as informações básicas da sua clínica.
        </p>
      </div>

      <div className="grid gap-6">
        <div className="grid gap-1.5">
          <Label htmlFor="name" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Nome da Clínica</Label>
          <div className="relative">
            <Building2 className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
            <Input id="name" {...register("name")} className="h-11 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
          </div>
          {errors.name && <p className="text-xs text-destructive font-sans font-medium">{errors.name.message as string}</p>}
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="email" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">E-mail de Contato</Label>
          <div className="relative">
            <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
            <Input id="email" type="email" {...register("email")} className="h-11 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
          </div>
          {errors.email && <p className="text-xs text-destructive font-sans font-medium">{errors.email.message as string}</p>}
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="phone" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Telefone / WhatsApp Principal</Label>
          <div className="relative">
            <Phone className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
            <Input id="phone" {...register("phone")} className="h-11 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" placeholder="(11) 99999-9999" />
          </div>
          {errors.phone && <p className="text-xs text-destructive font-sans font-medium">{errors.phone.message as string}</p>}
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="address" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Endereço Físico</Label>
          <div className="relative">
            <MapPin className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
            <Input id="address" {...register("address")} className="h-11 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" placeholder="Rua Exemplo, 123" />
          </div>
          {errors.address && <p className="text-xs text-destructive font-sans font-medium">{errors.address.message as string}</p>}
        </div>
      </div>

      <div className="flex items-center gap-4 pt-4 border-t border-white/5">
        <button type="submit" disabled={isPending} className="sofia-btn-gradient px-5 py-2.5 rounded-xl text-white font-bold text-xs shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center disabled:opacity-50">
          {isPending ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="mr-1.5 h-3.5 w-3.5" />
          )}
          Salvar Alterações
        </button>
        {isSuccess && <span className="text-xs text-emerald-400 font-sans font-semibold">Salvo com sucesso!</span>}
      </div>
    </form>
  );
}

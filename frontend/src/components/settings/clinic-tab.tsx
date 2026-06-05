"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { TenantProfile, useUpdateTenant } from "@/hooks/useSettings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { MapPin, Phone, Mail, Globe, CreditCard, Info, Save, Loader2, Plus, X } from "lucide-react";

const formSchema = z.object({
  address: z.string().optional(),
  phone: z.string().optional(),
  email: z.string().email("E-mail inválido").optional().or(z.literal("")),
  instagram: z.string().optional(),
  additional_info: z.string().optional(),
});

type FormValues = z.infer<typeof formSchema>;

const SUGGESTED_PAYMENT_METHODS = [
  "PIX",
  "Cartão de crédito",
  "Cartão de débito",
  "Dinheiro",
  "Transferência",
  "Boleto"
];

export function ClinicTab({ tenant }: { tenant: TenantProfile }) {
  const { mutateAsync: updateTenant, isPending } = useUpdateTenant();
  const [isSuccess, setIsSuccess] = useState(false);
  
  const defaultSettings = tenant.settings?.clinic || {};
  
  const [paymentMethods, setPaymentMethods] = useState<string[]>(
    defaultSettings.payment_methods || []
  );
  const [customMethod, setCustomMethod] = useState("");

  const { register, handleSubmit, formState: { errors } } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      address: defaultSettings.address || "",
      phone: defaultSettings.phone || "",
      email: defaultSettings.email || "",
      instagram: defaultSettings.instagram || "",
      additional_info: defaultSettings.additional_info || "",
    },
  });

  const handleAddPaymentMethod = (method: string) => {
    const trimmed = method.trim();
    if (trimmed && !paymentMethods.includes(trimmed)) {
      setPaymentMethods([...paymentMethods, trimmed]);
      setCustomMethod("");
    }
  };

  const handleRemovePaymentMethod = (methodToRemove: string) => {
    setPaymentMethods(paymentMethods.filter(m => m !== methodToRemove));
  };

  const onSubmit = async (data: FormValues) => {
    try {
      setIsSuccess(false);
      // Construct the full settings object to merge
      const newSettings = {
        ...(tenant.settings || {}),
        clinic: {
          address: data.address || undefined,
          phone: data.phone || undefined,
          email: data.email || undefined,
          instagram: data.instagram || undefined,
          additional_info: data.additional_info || undefined,
          payment_methods: paymentMethods.length > 0 ? paymentMethods : undefined,
        }
      };

      await updateTenant({ settings: newSettings });
      setIsSuccess(true);
      setTimeout(() => setIsSuccess(false), 3000);
    } catch (error) {
      console.error("Failed to update clinic settings", error);
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-6 max-w-3xl">
      <div>
        <h3 className="text-lg font-medium">Informações da Clínica</h3>
        <p className="text-sm text-muted-foreground mt-1">
          Essas informações ficam disponíveis para a Sofia responder perguntas dos pacientes (endereço, formas de pagamento, etc).
        </p>
      </div>

      <div className="grid gap-6">
        <div className="grid gap-3">
          <Label htmlFor="address">Endereço Completo</Label>
          <div className="relative">
            <MapPin className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
            <Input id="address" {...register("address")} className="pl-9" placeholder="Rua Exemplo, 123 - Bairro, Cidade - UF" />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="grid gap-3">
            <Label htmlFor="phone">Telefone / WhatsApp</Label>
            <div className="relative">
              <Phone className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <Input id="phone" {...register("phone")} className="pl-9" placeholder="(11) 99999-9999" />
            </div>
          </div>

          <div className="grid gap-3">
            <Label htmlFor="email">E-mail de Contato</Label>
            <div className="relative">
              <Mail className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <Input id="email" type="email" {...register("email")} className="pl-9" placeholder="contato@clinica.com.br" />
            </div>
            {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
          </div>

          <div className="grid gap-3">
            <Label htmlFor="instagram">Instagram</Label>
            <div className="relative">
              <Globe className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <Input id="instagram" {...register("instagram")} className="pl-9" placeholder="@suaclinica" />
            </div>
          </div>
        </div>

        <div className="grid gap-3 pt-2">
          <Label>Formas de Pagamento Aceitas</Label>
          
          <div className="flex flex-wrap gap-2 mb-2">
            {paymentMethods.map(method => (
              <Badge key={method} variant="secondary" className="px-3 py-1 text-sm flex items-center gap-1">
                {method}
                <button
                  type="button"
                  onClick={() => handleRemovePaymentMethod(method)}
                  className="hover:bg-muted-foreground/20 rounded-full p-0.5 transition-colors"
                >
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ))}
            {paymentMethods.length === 0 && (
              <span className="text-sm text-muted-foreground italic">Nenhuma forma de pagamento configurada.</span>
            )}
          </div>

          <div className="flex gap-2">
            <Input 
              placeholder="Adicionar outra forma..." 
              value={customMethod}
              onChange={(e) => setCustomMethod(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleAddPaymentMethod(customMethod);
                }
              }}
              className="max-w-xs"
            />
            <Button 
              type="button" 
              variant="outline" 
              onClick={() => handleAddPaymentMethod(customMethod)}
              disabled={!customMethod.trim()}
            >
              <Plus className="h-4 w-4 mr-1" /> Adicionar
            </Button>
          </div>

          <div className="mt-2">
            <p className="text-xs text-muted-foreground mb-2">Sugestões rápidas:</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTED_PAYMENT_METHODS.filter(m => !paymentMethods.includes(m)).map(method => (
                <button
                  key={method}
                  type="button"
                  onClick={() => handleAddPaymentMethod(method)}
                  className="text-xs border border-dashed border-border/60 rounded-md px-2 py-1 text-muted-foreground hover:text-foreground hover:border-border transition-colors"
                >
                  + {method}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="grid gap-3 pt-2">
          <Label htmlFor="additional_info">Informações Adicionais</Label>
          <div className="relative">
            <Info className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
            <Textarea 
              id="additional_info" 
              {...register("additional_info")} 
              className="pl-9 min-h-[100px]" 
              placeholder="Estacionamento conveniado na rua de trás, prédio com acessibilidade para cadeirantes, etc."
            />
          </div>
        </div>
      </div>

      <div className="flex items-center gap-4 pt-4">
        <Button type="submit" disabled={isPending}>
          {isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          Salvar Informações
        </Button>
        {isSuccess && <span className="text-sm text-emerald-500 font-medium">Informações salvas com sucesso!</span>}
      </div>
    </form>
  );
}

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
import { MapPin, Phone, Mail, Globe, CreditCard, Info, Save, Loader2, Plus, X, CloudUpload, Edit, CheckCircle2, Sparkles, ArrowRight } from "lucide-react";

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
  // Max credit-card installments. Empty = not configured: Sofia will say the
  // installment plan is arranged at the clinic instead of inventing a number.
  const [maxInstallments, setMaxInstallments] = useState<string>(
    defaultSettings.max_installments ? String(defaultSettings.max_installments) : ""
  );

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
          max_installments:
            maxInstallments && Number(maxInstallments) >= 2
              ? Math.min(24, Math.floor(Number(maxInstallments)))
              : undefined,
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
    <form onSubmit={handleSubmit(onSubmit)} className="w-full">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
        
        {/* Left Column: Logo Upload & Visual Identity */}
        <div className="md:col-span-1 space-y-6">
          <section className="glass-panel rounded-3xl p-6 border border-white/10 bg-white/[0.02] flex flex-col items-center text-center shadow-2xl relative">
            <h3 className="font-heading text-sm font-semibold text-foreground mb-6 self-start">Logo da Clínica</h3>
            <div className="relative group cursor-pointer">
              <div className="w-40 h-40 rounded-full border-2 border-dashed border-primary/30 flex items-center justify-center bg-background/55 group-hover:border-primary/60 transition-all overflow-hidden">
                <div className="flex flex-col items-center gap-2 group-hover:scale-105 transition-transform">
                  <CloudUpload className="h-10 w-10 text-primary/50" />
                  <span className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground/80">Upload PNG/JPG</span>
                </div>
                <input className="absolute inset-0 opacity-0 cursor-pointer" type="file" disabled />
              </div>
              <div className="absolute -bottom-2 -right-2 w-10 h-10 bg-primary rounded-full flex items-center justify-center shadow-lg text-primary-foreground border border-white/10">
                <Edit className="h-4 w-4" />
              </div>
            </div>
            <p className="text-xs text-muted-foreground/80 font-sans mt-6 italic leading-relaxed">
              "A logo é a primeira impressão visual da sua excelência clínica."
            </p>
            <div className="mt-8 pt-6 border-t border-white/5 w-full flex flex-col gap-4 items-start">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-primary animate-pulse"></div>
                <span className="font-mono text-[10px] uppercase tracking-wider text-primary font-bold">Sugestão da Sofia</span>
              </div>
              <p className="text-xs text-muted-foreground/80 text-left leading-relaxed">
                Recomendo uma imagem com fundo transparente e proporção 1:1 para melhor exibição no portal de agendamento.
              </p>
            </div>
          </section>
        </div>

        {/* Right Column: Form Fields & Insights */}
        <div className="md:col-span-2 space-y-6">
          <section className="glass-panel rounded-3xl p-8 border border-white/10 bg-white/[0.02] shadow-2xl">
            <div className="flex items-center justify-between mb-8">
              <h3 className="font-heading text-lg font-bold text-foreground">Dados da Clínica</h3>
              <span className="bg-emerald-500/10 text-emerald-400 px-3 py-1 rounded-full font-mono text-[10px] uppercase tracking-wider border border-emerald-500/20 flex items-center gap-1.5 font-semibold">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Visível Publicamente
              </span>
            </div>

            <div className="space-y-6">
              {/* Endereço Completo */}
              <div className="grid gap-1.5">
                <Label htmlFor="address" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Endereço Completo</Label>
                <div className="relative">
                  <MapPin className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
                  <Input 
                    id="address" 
                    {...register("address")} 
                    className="h-12 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full placeholder:text-muted-foreground/60" 
                    placeholder="Av. Paulista, 1000 - Bela Vista, São Paulo - SP, 01310-100" 
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* WhatsApp */}
                <div className="grid gap-1.5">
                  <Label htmlFor="phone" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">WhatsApp (Contato)</Label>
                  <div className="relative">
                    <Phone className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
                    <Input 
                      id="phone" 
                      {...register("phone")} 
                      className="h-12 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full placeholder:text-muted-foreground/60" 
                      placeholder="+55 (11) 98765-4321" 
                    />
                  </div>
                </div>

                {/* E-mail */}
                <div className="grid gap-1.5">
                  <Label htmlFor="email" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">E-mail Público</Label>
                  <div className="relative">
                    <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
                    <Input 
                      id="email" 
                      type="email" 
                      {...register("email")} 
                      className="h-12 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full placeholder:text-muted-foreground/60" 
                      placeholder="contato@luminahealth.com" 
                    />
                  </div>
                  {errors.email && <p className="text-xs text-destructive font-sans font-medium">{errors.email.message as string}</p>}
                </div>
              </div>

              {/* Redes Sociais */}
              <div className="grid gap-1.5">
                <Label htmlFor="instagram" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Redes Sociais (Instagram)</Label>
                <div className="relative">
                  <Globe className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
                  <Input 
                    id="instagram" 
                    {...register("instagram")} 
                    className="h-12 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full placeholder:text-muted-foreground/60" 
                    placeholder="@suaclinica" 
                  />
                </div>
              </div>

              {/* Formas de Pagamento Aceitas */}
              <div className="grid gap-3 pt-2">
                <Label className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Formas de Pagamento Aceitas</Label>
                
                <div className="flex flex-wrap gap-2 mb-2">
                  {paymentMethods.map(method => (
                    <Badge key={method} variant="secondary" className="px-3 py-1.5 text-xs flex items-center gap-1.5 bg-primary/10 text-primary border border-primary/20 rounded-lg shadow-sm font-semibold">
                      {method}
                      <button
                        type="button"
                        onClick={() => handleRemovePaymentMethod(method)}
                        className="hover:bg-primary/20 rounded-full p-0.5 transition-colors cursor-pointer"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))}
                  {paymentMethods.length === 0 && (
                    <span className="text-xs text-muted-foreground italic font-sans">Nenhuma forma de pagamento configurada.</span>
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
                    className="max-w-xs h-12 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all"
                  />
                  <Button 
                    type="button" 
                    variant="outline" 
                    onClick={() => handleAddPaymentMethod(customMethod)}
                    disabled={!customMethod.trim()}
                    className="h-12 border-white/10 bg-white/5 hover:bg-white/10 text-muted-foreground hover:text-foreground cursor-pointer rounded-xl font-semibold text-xs transition-all px-4"
                  >
                    <Plus className="h-4 w-4 mr-1" /> Adicionar
                  </Button>
                </div>

                <div className="mt-2">
                  <p className="text-[11px] font-mono uppercase tracking-wider text-muted-foreground/60 mb-2">Sugestões rápidas:</p>
                  <div className="flex flex-wrap gap-2">
                    {SUGGESTED_PAYMENT_METHODS.filter(m => !paymentMethods.includes(m)).map(method => (
                      <button
                        key={method}
                        type="button"
                        onClick={() => handleAddPaymentMethod(method)}
                        className="text-xs border border-dashed border-white/10 rounded-xl px-3 py-1.5 text-muted-foreground hover:text-foreground hover:bg-white/5 hover:border-white/20 transition-all font-sans cursor-pointer"
                      >
                        + {method}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Max installments — structured data so Sofia never invents "até 3x" */}
                <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                  <Label htmlFor="max_installments" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 flex items-center gap-2">
                    <CreditCard className="h-3.5 w-3.5 text-muted-foreground/60" />
                    Parcelamento máximo no cartão de crédito
                  </Label>
                  <div className="mt-2 flex items-center gap-3">
                    <Input
                      id="max_installments"
                      type="number"
                      min={2}
                      max={24}
                      value={maxInstallments}
                      onChange={(e) => setMaxInstallments(e.target.value)}
                      placeholder="Ex: 3"
                      className="h-12 w-28 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all"
                    />
                    <span className="text-xs text-muted-foreground font-sans">vezes sem informar = a Sofia dirá que o parcelamento é combinado na clínica</span>
                  </div>
                  <p className="text-[11px] text-muted-foreground/70 font-sans mt-2 leading-relaxed">
                    A Sofia só informa parcelamento aos pacientes se este número estiver preenchido — ela nunca inventa condições de pagamento.
                  </p>
                </div>
              </div>

              {/* Informações Adicionais */}
              <div className="grid gap-1.5 pt-2">
                <Label htmlFor="additional_info" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Informações Adicionais</Label>
                <div className="relative">
                  <Info className="absolute left-3.5 top-3.5 h-4 w-4 text-muted-foreground/60" />
                  <Textarea 
                    id="additional_info" 
                    {...register("additional_info")} 
                    className="pl-10 min-h-[100px] rounded-xl border border-white/10 bg-background/55 text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 w-full" 
                    placeholder="Estacionamento conveniado na rua de trás, prédio com acessibilidade para cadeirantes, etc."
                  />
                </div>
              </div>
            </div>

            {/* Action Buttons inside Card matching Discard/Save mockups layout */}
            <div className="pt-8 flex justify-end gap-4 border-t border-white/5 mt-6">
              <button 
                type="submit" 
                disabled={isPending} 
                className="px-8 py-3 bg-gradient-to-r from-primary to-secondary text-on-primary font-bold rounded-xl shadow-lg shadow-primary/20 hover:scale-[1.02] active:scale-[0.98] transition-all flex items-center gap-2 cursor-pointer text-xs disabled:opacity-50"
              >
                {isPending ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="mr-1.5 h-3.5 w-3.5" />
                )}
                Salvar Alterações
              </button>
            </div>
            {isSuccess && (
              <div className="mt-3 text-right">
                <span className="text-xs text-emerald-400 font-sans font-semibold">Informações salvas com sucesso!</span>
              </div>
            )}
          </section>

          {/* Sofia Insights Card */}
          <section className="glass-panel rounded-3xl p-6 border border-white/10 bg-white/[0.02] overflow-hidden relative group shadow-2xl">
            <div className="absolute -right-4 -top-4 w-32 h-32 bg-primary/10 blur-3xl rounded-full group-hover:bg-primary/20 transition-all pointer-events-none" />
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-2xl bg-primary/20 flex items-center justify-center shrink-0 border border-primary/30 text-primary">
                <Sparkles className="h-6 w-6 text-primary" />
              </div>
              <div className="space-y-2">
                <h4 className="font-heading text-sm font-semibold text-primary">Análise de Presença Online</h4>
                <p className="text-xs text-muted-foreground/80 leading-relaxed font-sans">
                  Notei que seu perfil está <span className="text-[#fbabff] font-bold">85% completo</span>. Adicionar o link do seu Instagram pode aumentar a taxa de conversão de novos agendamentos em até <span className="text-primary font-bold">12%</span> com base em perfis similares.
                </p>
                <button
                  type="button"
                  className="mt-4 flex items-center gap-1.5 text-primary font-mono text-[10px] uppercase tracking-wider hover:underline decoration-primary/30 underline-offset-4 cursor-pointer"
                >
                  Aplicar melhorias sugeridas
                  <ArrowRight className="h-3 w-3" />
                </button>
              </div>
            </div>
          </section>
        </div>

      </div>
    </form>
  );
}

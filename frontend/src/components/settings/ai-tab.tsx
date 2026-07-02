"use client";

import { useState } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { TenantProfile, useUpdateTenant } from "@/hooks/useSettings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";
import { Bot, MessageSquare, SlidersHorizontal, Save, Loader2, Sparkles } from "lucide-react";

const formSchema = z.object({
  model: z.string().min(1, "Obrigatório"),
  temperature: z.coerce.number().min(0).max(2).optional(),
  max_output_tokens: z.coerce.number().min(100).optional(),
  system_prompt: z.string().min(10, "O prompt deve ter no mínimo 10 caracteres"),
  multimodal_enabled: z.boolean().default(false),
  prompt_first_contact: z.string().optional(),
  prompt_imminent_appointment: z.string().optional(),
  prompt_post_appointment: z.string().optional(),
  prompt_active_patient: z.string().optional(),
  prompt_returning_lead: z.string().optional(),
  prompt_reactivation: z.string().optional(),
});

type FormValues = z.infer<typeof formSchema>;

export function AiTab({ tenant }: { tenant: TenantProfile }) {
  const { mutateAsync: updateTenant, isPending } = useUpdateTenant();
  const [isSuccess, setIsSuccess] = useState(false);

  const defaultValues = tenant.ai_config || {
    model: "gemini-2.0-flash",
    system_prompt: "Você é Sofia, a secretária virtual da clínica. Seja sempre educada e ajude os pacientes a marcar consultas.",
    temperature: 0.7,
    max_output_tokens: 1024,
  };

  const { register, handleSubmit, control, formState: { errors } } = useForm<z.infer<typeof formSchema>>({
    resolver: zodResolver(formSchema) as any,
    defaultValues: {
      model: defaultValues.model || "gemini-2.0-flash",
      system_prompt: defaultValues.system_prompt || "",
      temperature: defaultValues.temperature || 0.7,
      max_output_tokens: defaultValues.max_output_tokens || 1024,
      multimodal_enabled: defaultValues.multimodal_enabled || false,
      prompt_first_contact: defaultValues.prompt_first_contact || "",
      prompt_imminent_appointment: defaultValues.prompt_imminent_appointment || "",
      prompt_post_appointment: defaultValues.prompt_post_appointment || "",
      prompt_active_patient: defaultValues.prompt_active_patient || "",
      prompt_returning_lead: defaultValues.prompt_returning_lead || "",
      prompt_reactivation: defaultValues.prompt_reactivation || "",
    },
  });

  const onSubmit = async (data: FormValues) => {
    try {
      setIsSuccess(false);
      // Send explicit values (empty string clears) so the backend top-level merge
      // overwrites these keys instead of keeping stale ones. Unmanaged keys like
      // `scheduling_mode` are preserved by the merge.
      await updateTenant({
        ai_config: {
          model: data.model,
          system_prompt: data.system_prompt,
          temperature: data.temperature,
          max_output_tokens: data.max_output_tokens,
          multimodal_enabled: data.multimodal_enabled,
          prompt_first_contact: data.prompt_first_contact || "",
          prompt_imminent_appointment: data.prompt_imminent_appointment || "",
          prompt_post_appointment: data.prompt_post_appointment || "",
          prompt_active_patient: data.prompt_active_patient || "",
          prompt_returning_lead: data.prompt_returning_lead || "",
          prompt_reactivation: data.prompt_reactivation || "",
        }
      });
      setIsSuccess(true);
      setTimeout(() => setIsSuccess(false), 3000);
    } catch (error) {
      console.error("Failed to update AI settings", error);
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-6 max-w-3xl bg-background/5">
      <div>
        <h3 className="font-heading text-lg font-bold text-foreground">Inteligência Artificial (Sofia)</h3>
        <p className="text-xs text-muted-foreground/80 font-sans mt-0.5">
          Configure a personalidade, o tom de voz e as regras de negócio da sua secretária virtual.
        </p>
      </div>

      <div className="grid gap-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="grid gap-1.5">
            <Label htmlFor="model" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Modelo de IA</Label>
            <div className="relative">
              <Bot className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
              <Input id="model" {...register("model")} className="h-11 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
            </div>
            {errors.model && <p className="text-xs text-destructive font-sans font-medium">{errors.model.message as string}</p>}
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="temperature" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Temperatura (0 a 2)</Label>
            <div className="relative">
              <SlidersHorizontal className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
              <Input id="temperature" type="number" step="0.1" {...register("temperature")} className="h-11 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
            </div>
            {errors.temperature && <p className="text-xs text-destructive font-sans font-medium">{errors.temperature.message as string}</p>}
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="max_output_tokens" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Max Tokens</Label>
            <div className="relative">
              <MessageSquare className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/60" />
              <Input id="max_output_tokens" type="number" {...register("max_output_tokens")} className="h-11 pl-10 rounded-xl border-white/10 bg-background/55 text-foreground text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
            </div>
            {errors.max_output_tokens && <p className="text-xs text-destructive font-sans font-medium">{errors.max_output_tokens.message as string}</p>}
          </div>
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="system_prompt" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Prompt base — identidade da Sofia</Label>
          <Textarea 
            id="system_prompt" 
            {...register("system_prompt")} 
            className="min-h-[200px] font-mono text-sm leading-relaxed p-4 rounded-xl border border-white/10 bg-background/55 text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 w-full" 
            placeholder="Você é a Sofia, secretária da clínica..."
          />
          <p className="text-[11px] text-muted-foreground/80 font-sans leading-relaxed">
            Descreva como a IA deve se comportar, qual o tom de voz e restrições importantes. Ela já sabe as ferramentas de agendamento por padrão.
          </p>
          {errors.system_prompt && <p className="text-xs text-destructive font-sans font-medium">{errors.system_prompt.message as string}</p>}
        </div>

        <div className="flex flex-row items-center justify-between rounded-2xl border border-white/10 p-4 bg-white/5 shadow-md">
          <div className="space-y-0.5">
            <Label className="font-heading text-sm font-semibold text-foreground flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary animate-pulse" />
              IA Multimodal (Áudio, Imagem e Documentos)
            </Label>
            <p className="text-xs text-muted-foreground/80 font-sans mt-0.5 leading-relaxed">
              Permite que a Sofia interprete áudios (até 1m30s), imagens, vídeos e documentos enviados pelos pacientes. Aumenta o custo por mensagem.
            </p>
          </div>
          <Controller
            name="multimodal_enabled"
            control={control}
            render={({ field }) => (
              <Switch checked={field.value} onCheckedChange={field.onChange} className="cursor-pointer" />
            )}
          />
        </div>

        <div className="grid gap-3 pt-2">
          <div className="flex flex-col gap-1">
            <Label className="font-heading text-base font-semibold text-foreground">Prompts por estágio da conversa</Label>
            <p className="text-xs text-muted-foreground/80 font-sans leading-relaxed">
              A Sofia detecta o contexto do paciente e injeta essas instruções adicionais no prompt base. Se deixar vazio, ela usará o texto padrão.
            </p>
          </div>

          <Accordion className="w-full border border-white/10 rounded-2xl bg-white/5 overflow-hidden shadow-md">
            <AccordionItem value="first_contact" className="border-b border-white/10">
              <AccordionTrigger className="px-4 hover:bg-white/5 transition-colors">
                <div className="flex flex-col items-start gap-0.5 text-left">
                  <span className="font-heading text-sm font-semibold text-foreground">Primeiro contato</span>
                  <span className="text-xs text-muted-foreground/70 font-sans font-normal">quando o paciente nunca mandou mensagem antes</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="px-4 pb-4 pt-2">
                <Textarea 
                  {...register("prompt_first_contact")} 
                  className="min-h-[120px] rounded-xl border border-white/10 bg-background/55 text-foreground p-3 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 w-full font-sans leading-relaxed" 
                  placeholder={"Esta é a PRIMEIRA conversa deste paciente com a clínica.\n- Apresente-se brevemente como Sofia, a secretária virtual.\n- Pergunte como pode ajudar de forma acolhedora.\n- Se o paciente já mandou uma dúvida concreta, vá direto resolvendo — não obrigue a passar por uma apresentação se ele já está pedindo algo."}
                />
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="imminent_appointment" className="border-b border-white/10">
              <AccordionTrigger className="px-4 hover:bg-white/5 transition-colors">
                <div className="flex flex-col items-start gap-0.5 text-left">
                  <span className="font-heading text-sm font-semibold text-foreground">Agendamento próximo</span>
                  <span className="text-xs text-muted-foreground/70 font-sans font-normal">quando o paciente tem consulta nas próximas 48h</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="px-4 pb-4 pt-2">
                <Textarea 
                  {...register("prompt_imminent_appointment")} 
                  className="min-h-[120px] rounded-xl border border-white/10 bg-background/55 text-foreground p-3 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 w-full font-sans leading-relaxed" 
                  placeholder={"O paciente TEM um agendamento confirmado nas próximas 48 horas.\n- É provável que esteja entrando em contato sobre isso (confirmar, remarcar ou cancelar).\n- Use get_upcoming_appointments para ver os detalhes antes de responder.\n- Se ele quiser remarcar, use reschedule_appointment (não cancela e cria de novo)."}
                />
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="post_appointment" className="border-b border-white/10">
              <AccordionTrigger className="px-4 hover:bg-white/5 transition-colors">
                <div className="flex flex-col items-start gap-0.5 text-left">
                  <span className="font-heading text-sm font-semibold text-foreground">Pós-atendimento</span>
                  <span className="text-xs text-muted-foreground/70 font-sans font-normal">quando o paciente teve consulta nas últimas 48h</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="px-4 pb-4 pt-2">
                <Textarea 
                  {...register("prompt_post_appointment")} 
                  className="min-h-[120px] rounded-xl border border-white/10 bg-background/55 text-foreground p-3 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 w-full font-sans leading-relaxed" 
                  placeholder={"O paciente teve um atendimento nas últimas 48 horas.\n- Demonstre interesse em saber como foi.\n- Se for serviço recorrente (ex: limpeza, manutenção), ofereça já agendar o próximo.\n- Não force vendas — escute primeiro."}
                />
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="active_patient" className="border-b border-white/10">
              <AccordionTrigger className="px-4 hover:bg-white/5 transition-colors">
                <div className="flex flex-col items-start gap-0.5 text-left">
                  <span className="font-heading text-sm font-semibold text-foreground">Paciente recorrente</span>
                  <span className="text-xs text-muted-foreground/70 font-sans font-normal">quando o paciente já tem consultas concluídas no histórico</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="px-4 pb-4 pt-2">
                <Textarea 
                  {...register("prompt_active_patient")} 
                  className="min-h-[120px] rounded-xl border border-white/10 bg-background/55 text-foreground p-3 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 w-full font-sans leading-relaxed" 
                  placeholder={"Paciente já é recorrente da clínica.\n- Use tom mais íntimo e familiar — vocês já se conhecem.\n- Não repita explicações longas sobre serviços que ele já fez antes.\n- Vá direto ao ponto."}
                />
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="returning_lead" className="border-b border-white/10">
              <AccordionTrigger className="px-4 hover:bg-white/5 transition-colors">
                <div className="flex flex-col items-start gap-0.5 text-left">
                  <span className="font-heading text-sm font-semibold text-foreground">Lead recorrente</span>
                  <span className="text-xs text-muted-foreground/70 font-sans font-normal">quando o paciente já conversou mas nunca agendou</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="px-4 pb-4 pt-2">
                <Textarea 
                  {...register("prompt_returning_lead")} 
                  className="min-h-[120px] rounded-xl border border-white/10 bg-background/55 text-foreground p-3 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 w-full font-sans leading-relaxed" 
                  placeholder={"Paciente já conversou antes mas NUNCA agendou.\n- Seja proativa: apresente serviços e sugira datas.\n- Se houver hesitação, ofereça alternativas (horário, valor, formato).\n- Use list_services e check_availability sem esperar pedido explícito."}
                />
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="reactivation" className="border-b-0">
              <AccordionTrigger className="px-4 hover:bg-white/5 transition-colors">
                <div className="flex flex-col items-start gap-0.5 text-left">
                  <span className="font-heading text-sm font-semibold text-foreground">Reativação</span>
                  <span className="text-xs text-muted-foreground/70 font-sans font-normal">quando o paciente sumiu há mais de 30 dias</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="px-4 pb-4 pt-2">
                <Textarea 
                  {...register("prompt_reactivation")} 
                  className="min-h-[120px] rounded-xl border border-white/10 bg-background/55 text-foreground p-3 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 w-full font-sans leading-relaxed" 
                  placeholder={"Paciente sumiu há mais de 30 dias.\n- Receba com tom acolhedor: 'que bom ter você de volta!'.\n- Pergunte como pode ajudar agora; não pressione.\n- Se for serviço recorrente, antecipe e sugira já agendar."}
                />
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </div>
      </div>

      <div className="flex items-center gap-4 pt-4 border-t border-white/5">
        <button type="submit" disabled={isPending} className="sofia-btn-gradient px-5 py-2.5 rounded-xl text-white font-bold text-xs shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center disabled:opacity-50">
          {isPending ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="mr-1.5 h-3.5 w-3.5" />
          )}
          Salvar Inteligência Artificial
        </button>
        {isSuccess && <span className="text-xs text-emerald-400 font-sans font-semibold">Configurações salvas com sucesso!</span>}
      </div>
    </form>
  );
}

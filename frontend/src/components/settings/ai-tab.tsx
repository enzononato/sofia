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
import { Switch } from "@/components/ui/switch";
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";
import { Bot, Key, MessageSquare, SlidersHorizontal, Save, Loader2, Sparkles } from "lucide-react";

const formSchema = z.object({
  model: z.string().min(1, "Obrigatório"),
  gemini_api_key: z.string().optional(),
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
    gemini_api_key: "",
  };

  const { register, handleSubmit, watch, formState: { errors } } = useForm<z.infer<typeof formSchema>>({
    resolver: zodResolver(formSchema) as any,
    defaultValues: {
      model: defaultValues.model || "gemini-2.0-flash",
      gemini_api_key: defaultValues.gemini_api_key || "",
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
          gemini_api_key: data.gemini_api_key || "",
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
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-6 max-w-3xl">
      <div>
        <h3 className="text-lg font-medium">Inteligência Artificial (Sofia)</h3>
        <p className="text-sm text-muted-foreground mt-1">
          Configure a personalidade, as regras de negócio e as chaves de acesso da sua secretária virtual.
        </p>
      </div>

      <div className="grid gap-6">
        <div className="grid gap-3">
          <Label htmlFor="gemini_api_key">Google Gemini API Key (Opcional)</Label>
          <div className="relative">
            <Key className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
            <Input id="gemini_api_key" type="password" {...register("gemini_api_key")} className="pl-9" placeholder="Se vazio, usará a chave global do sistema" />
          </div>
          <p className="text-xs text-muted-foreground">Recomendado inserir uma chave própria para não dividir limites de uso.</p>
          {errors.gemini_api_key && <p className="text-sm text-destructive">{errors.gemini_api_key.message}</p>}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="grid gap-3">
            <Label htmlFor="model">Modelo de IA</Label>
            <div className="relative">
              <Bot className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <Input id="model" {...register("model")} className="pl-9" />
            </div>
            {errors.model && <p className="text-sm text-destructive">{errors.model.message}</p>}
          </div>

          <div className="grid gap-3">
            <Label htmlFor="temperature">Temperatura (0 a 2)</Label>
            <div className="relative">
              <SlidersHorizontal className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <Input id="temperature" type="number" step="0.1" {...register("temperature")} className="pl-9" />
            </div>
            {errors.temperature && <p className="text-sm text-destructive">{errors.temperature.message}</p>}
          </div>

          <div className="grid gap-3">
            <Label htmlFor="max_output_tokens">Max Tokens</Label>
            <div className="relative">
              <MessageSquare className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <Input id="max_output_tokens" type="number" {...register("max_output_tokens")} className="pl-9" />
            </div>
            {errors.max_output_tokens && <p className="text-sm text-destructive">{errors.max_output_tokens.message}</p>}
          </div>
        </div>

        <div className="grid gap-3">
          <Label htmlFor="system_prompt">Prompt base — identidade da Sofia</Label>
          <Textarea 
            id="system_prompt" 
            {...register("system_prompt")} 
            className="min-h-[250px] font-mono text-sm leading-relaxed p-4" 
            placeholder="Você é a Sofia, secretária da clínica..."
          />
          <p className="text-xs text-muted-foreground">
            Descreva como a IA deve se comportar, qual o tom de voz e restrições importantes. Ela já sabe as ferramentas de agendamento por padrão.
          </p>
          {errors.system_prompt && <p className="text-sm text-destructive">{errors.system_prompt.message}</p>}
        </div>

        <div className="flex flex-row items-center justify-between rounded-lg border border-border/50 p-4 bg-muted/20">
          <div className="space-y-0.5">
            <Label className="text-base flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-amber-500" />
              IA Multimodal (Áudio, Imagem e Documentos)
            </Label>
            <p className="text-sm text-muted-foreground">
              Permite que a Sofia interprete áudios (até 1m30s), imagens, vídeos e documentos enviados pelos pacientes. Aumenta o custo por mensagem.
            </p>
          </div>
          <Switch
            checked={watch("multimodal_enabled")}
            onCheckedChange={(checked) => register("multimodal_enabled").onChange({ target: { name: "multimodal_enabled", value: checked } })}
          />
        </div>

        <div className="grid gap-3 pt-2">
          <div className="flex flex-col gap-1">
            <Label className="text-base font-semibold">Prompts por estágio da conversa</Label>
            <p className="text-sm text-muted-foreground">
              A Sofia detecta o contexto do paciente e injeta essas instruções adicionais no prompt base. Se deixar vazio, ela usará o texto padrão.
            </p>
          </div>

          <Accordion className="w-full border border-border/50 rounded-lg bg-card">
            <AccordionItem value="first_contact">
              <AccordionTrigger className="px-4 hover:bg-muted/50 rounded-t-lg">
                <div className="flex flex-col items-start gap-1">
                  <span>Primeiro contato</span>
                  <span className="text-xs text-muted-foreground font-normal">quando o paciente nunca mandou mensagem antes</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="px-4 pb-4 pt-2">
                <Textarea 
                  {...register("prompt_first_contact")} 
                  className="min-h-[120px] text-sm" 
                  placeholder={"Esta é a PRIMEIRA conversa deste paciente com a clínica.\n- Apresente-se brevemente como Sofia, a secretária virtual.\n- Pergunte como pode ajudar de forma acolhedora.\n- Se o paciente já mandou uma dúvida concreta, vá direto resolvendo — não obrigue a passar por uma apresentação se ele já está pedindo algo."}
                />
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="imminent_appointment">
              <AccordionTrigger className="px-4 hover:bg-muted/50">
                <div className="flex flex-col items-start gap-1">
                  <span>Agendamento próximo</span>
                  <span className="text-xs text-muted-foreground font-normal">quando o paciente tem consulta nas próximas 48h</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="px-4 pb-4 pt-2">
                <Textarea 
                  {...register("prompt_imminent_appointment")} 
                  className="min-h-[120px] text-sm" 
                  placeholder={"O paciente TEM um agendamento confirmado nas próximas 48 horas.\n- É provável que esteja entrando em contato sobre isso (confirmar, remarcar ou cancelar).\n- Use get_upcoming_appointments para ver os detalhes antes de responder.\n- Se ele quiser remarcar, use reschedule_appointment (não cancela e cria de novo)."}
                />
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="post_appointment">
              <AccordionTrigger className="px-4 hover:bg-muted/50">
                <div className="flex flex-col items-start gap-1">
                  <span>Pós-atendimento</span>
                  <span className="text-xs text-muted-foreground font-normal">quando o paciente teve consulta nas últimas 48h</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="px-4 pb-4 pt-2">
                <Textarea 
                  {...register("prompt_post_appointment")} 
                  className="min-h-[120px] text-sm" 
                  placeholder={"O paciente teve um atendimento nas últimas 48 horas.\n- Demonstre interesse em saber como foi.\n- Se for serviço recorrente (ex: limpeza, manutenção), ofereça já agendar o próximo.\n- Não force vendas — escute primeiro."}
                />
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="active_patient">
              <AccordionTrigger className="px-4 hover:bg-muted/50">
                <div className="flex flex-col items-start gap-1">
                  <span>Paciente recorrente</span>
                  <span className="text-xs text-muted-foreground font-normal">quando o paciente já tem consultas concluídas no histórico</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="px-4 pb-4 pt-2">
                <Textarea 
                  {...register("prompt_active_patient")} 
                  className="min-h-[120px] text-sm" 
                  placeholder={"Paciente já é recorrente da clínica.\n- Use tom mais íntimo e familiar — vocês já se conhecem.\n- Não repita explicações longas sobre serviços que ele já fez antes.\n- Vá direto ao ponto."}
                />
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="returning_lead">
              <AccordionTrigger className="px-4 hover:bg-muted/50">
                <div className="flex flex-col items-start gap-1">
                  <span>Lead recorrente</span>
                  <span className="text-xs text-muted-foreground font-normal">quando o paciente já conversou mas nunca agendou</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="px-4 pb-4 pt-2">
                <Textarea 
                  {...register("prompt_returning_lead")} 
                  className="min-h-[120px] text-sm" 
                  placeholder={"Paciente já conversou antes mas NUNCA agendou.\n- Seja proativa: apresente serviços e sugira datas.\n- Se houver hesitação, ofereça alternativas (horário, valor, formato).\n- Use list_services e check_availability sem esperar pedido explícito."}
                />
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="reactivation" className="border-b-0">
              <AccordionTrigger className="px-4 hover:bg-muted/50 rounded-b-lg">
                <div className="flex flex-col items-start gap-1">
                  <span>Reativação</span>
                  <span className="text-xs text-muted-foreground font-normal">quando o paciente sumiu há mais de 30 dias</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="px-4 pb-4 pt-2">
                <Textarea 
                  {...register("prompt_reactivation")} 
                  className="min-h-[120px] text-sm" 
                  placeholder={"Paciente sumiu há mais de 30 dias.\n- Receba com tom acolhedor: 'que bom ter você de volta!'.\n- Pergunte como pode ajudar agora; não pressione.\n- Se for serviço recorrente, antecipe e sugira já agendar."}
                />
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </div>
      </div>

      <div className="flex items-center gap-4 pt-4">
        <Button type="submit" disabled={isPending}>
          {isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          Salvar Inteligência Artificial
        </Button>
        {isSuccess && <span className="text-sm text-emerald-500 font-medium">Configurações salvas com sucesso!</span>}
      </div>
    </form>
  );
}

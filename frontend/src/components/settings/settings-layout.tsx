"use client";

import { useTenantProfile } from "@/hooks/useSettings";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Building2, MessageCircle, Bot, Clock, Store, BellRing } from "lucide-react";
import { GeneralTab } from "./general-tab";
import { ClinicTab } from "./clinic-tab";
import { WhatsappTab } from "./whatsapp-tab";
import { AiTab } from "./ai-tab";
import { ScheduleTab } from "./schedule-tab";
import { FollowupsTab } from "./followups-tab";

export function SettingsLayout() {
  const { data: tenant, isLoading } = useTenantProfile();

  if (isLoading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-10 w-[400px] bg-muted rounded-lg"></div>
        <div className="h-[400px] bg-muted/30 rounded-xl border border-border/50"></div>
      </div>
    );
  }

  if (!tenant) {
    return <div>Erro ao carregar as configurações.</div>;
  }

  return (
    <Tabs defaultValue="general" className="w-full">
      <div className="overflow-x-auto pb-2 mb-6">
        <TabsList className="bg-white/5 border border-white/10 p-1 w-full sm:w-auto inline-flex h-auto gap-1 rounded-2xl shadow-md">
          <TabsTrigger value="general" className="gap-2 py-2.5 px-4 rounded-xl text-[10px] font-mono uppercase tracking-wider font-bold transition-all data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-lg data-[state=active]:shadow-primary/20 text-muted-foreground hover:text-foreground cursor-pointer">
            <Store className="h-4 w-4" />
            <span className="hidden sm:inline">Perfil do Sistema</span>
            <span className="sm:hidden">Sistema</span>
          </TabsTrigger>
          <TabsTrigger value="clinic" className="gap-2 py-2.5 px-4 rounded-xl text-[10px] font-mono uppercase tracking-wider font-bold transition-all data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-lg data-[state=active]:shadow-primary/20 text-muted-foreground hover:text-foreground cursor-pointer">
            <Building2 className="h-4 w-4" />
            <span className="hidden sm:inline">Informações Públicas</span>
            <span className="sm:hidden">Clínica</span>
          </TabsTrigger>
          <TabsTrigger value="whatsapp" className="gap-2 py-2.5 px-4 rounded-xl text-[10px] font-mono uppercase tracking-wider font-bold transition-all data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-lg data-[state=active]:shadow-primary/20 text-muted-foreground hover:text-foreground cursor-pointer">
            <MessageCircle className="h-4 w-4" />
            <span className="hidden sm:inline">Integração WhatsApp</span>
            <span className="sm:hidden">WhatsApp</span>
          </TabsTrigger>
          <TabsTrigger value="ai" className="gap-2 py-2.5 px-4 rounded-xl text-[10px] font-mono uppercase tracking-wider font-bold transition-all data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-lg data-[state=active]:shadow-primary/20 text-muted-foreground hover:text-foreground cursor-pointer">
            <Bot className="h-4 w-4" />
            <span className="hidden sm:inline">Inteligência Artificial</span>
            <span className="sm:hidden">IA</span>
          </TabsTrigger>
          <TabsTrigger value="schedule" className="gap-2 py-2.5 px-4 rounded-xl text-[10px] font-mono uppercase tracking-wider font-bold transition-all data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-lg data-[state=active]:shadow-primary/20 text-muted-foreground hover:text-foreground cursor-pointer">
            <Clock className="h-4 w-4" />
            <span className="hidden sm:inline">Horários</span>
            <span className="sm:hidden">Agenda</span>
          </TabsTrigger>
          <TabsTrigger value="followups" className="gap-2 py-2.5 px-4 rounded-xl text-[10px] font-mono uppercase tracking-wider font-bold transition-all data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-lg data-[state=active]:shadow-primary/20 text-muted-foreground hover:text-foreground cursor-pointer">
            <BellRing className="h-4 w-4" />
            <span className="hidden sm:inline">Lembretes & Follow-up</span>
            <span className="sm:hidden">Follow-up</span>
          </TabsTrigger>
        </TabsList>
      </div>

      <div className="mt-6 bg-background/45 backdrop-blur-md border border-white/10 rounded-2xl p-6 shadow-xl relative overflow-hidden">
        <TabsContent value="general" className="m-0 focus-visible:outline-none focus-visible:ring-0">
          <GeneralTab tenant={tenant} />
        </TabsContent>
        <TabsContent value="clinic" className="m-0 focus-visible:outline-none focus-visible:ring-0">
          <ClinicTab tenant={tenant} />
        </TabsContent>
        <TabsContent value="whatsapp" className="m-0 focus-visible:outline-none focus-visible:ring-0">
          <WhatsappTab tenant={tenant} />
        </TabsContent>
        <TabsContent value="ai" className="m-0 focus-visible:outline-none focus-visible:ring-0">
          <AiTab tenant={tenant} />
        </TabsContent>
        <TabsContent value="schedule" className="m-0 focus-visible:outline-none focus-visible:ring-0">
          <ScheduleTab tenant={tenant} />
        </TabsContent>
        <TabsContent value="followups" className="m-0 focus-visible:outline-none focus-visible:ring-0">
          <FollowupsTab tenant={tenant} />
        </TabsContent>
      </div>
    </Tabs>
  );
}

import { SettingsLayout } from "@/components/settings/settings-layout";

export default function SettingsPage() {
  return (
    <div className="p-6 md:p-10 max-w-5xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Configurações</h1>
        <p className="text-muted-foreground mt-1 text-sm md:text-base">
          Gerencie o perfil da sua clínica, integrações de IA e as credenciais do WhatsApp.
        </p>
      </div>
      
      <SettingsLayout />
    </div>
  );
}

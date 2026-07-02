"use client";

import { useGoogleStatus, useConnectGoogle, useDisconnectGoogle } from "@/hooks/useGoogleCalendar";
import { Button } from "@/components/ui/button";
import { CalendarCheck2, Loader2, Link2 } from "lucide-react";

export function GoogleCalendarButton() {
  const { data: status, isLoading } = useGoogleStatus();
  const connect = useConnectGoogle();
  const disconnect = useDisconnectGoogle();

  // Hidden entirely when the server has no Google integration configured.
  if (isLoading || !status?.configured) return null;

  if (status.connected) {
    return (
      <Button
        variant="outline"
        size="sm"
        onClick={() => disconnect.mutate()}
        disabled={disconnect.isPending}
        className="h-8 rounded-full px-3 text-emerald-400 border-emerald-500/20 bg-emerald-500/5 hover:bg-emerald-500/10 transition-colors cursor-pointer text-xs font-medium"
        title="Desconectar Google Calendar"
      >
        {disconnect.isPending ? (
          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
        ) : (
          <CalendarCheck2 className="mr-1.5 h-3.5 w-3.5" />
        )}
        Google conectado
      </Button>
    );
  }

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() => connect.mutate()}
      disabled={connect.isPending}
      className="h-8 rounded-full px-3 border-white/10 bg-white/5 hover:bg-white/10 text-muted-foreground hover:text-foreground transition-all cursor-pointer text-xs font-medium"
      title="Sincronizar seus agendamentos com o Google Calendar"
    >
      {connect.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Link2 className="mr-1.5 h-3.5 w-3.5" />}
      Conectar Google Agenda
    </Button>
  );
}

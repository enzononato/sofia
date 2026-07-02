"use client";

import { useState, useEffect, useCallback } from "react";
import { TenantProfile, useUpdateTenant } from "@/hooks/useSettings";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import api from "@/lib/axios";
import {
  Wifi,
  WifiOff,
  Loader2,
  QrCode,
  RefreshCw,
  Unplug,
  CheckCircle2,
  AlertCircle,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";

type ConnectionStatus =
  | "not_configured"
  | "connecting"
  | "connected"
  | "disconnected"
  | "unknown"
  | "loading";

export function WhatsappTab({ tenant }: { tenant: TenantProfile }) {
  const [status, setStatus] = useState<ConnectionStatus>("loading");
  const [instanceName, setInstanceName] = useState<string | null>(null);
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [showDisconnectDialog, setShowDisconnectDialog] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPolling, setIsPolling] = useState(false);

  // Behaviour settings
  const [ignoreGroups, setIgnoreGroups] = useState<boolean>(
    tenant.settings?.ignore_groups ?? true
  );
  const { mutateAsync: updateTenant, isPending: isSavingBehaviour } = useUpdateTenant();

  // Fetch current status on mount
  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get("/tenants/me/whatsapp/status");
      setStatus(res.data.status);
      setInstanceName(res.data.instance);
      return res.data.status;
    } catch {
      setStatus("unknown");
      return "unknown";
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Poll while connecting
  useEffect(() => {
    if (!isPolling) return;

    const interval = setInterval(async () => {
      const currentStatus = await fetchStatus();
      if (currentStatus === "connected") {
        setIsPolling(false);
        setQrCode(null);
        setIsConnecting(false);
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [isPolling, fetchStatus]);

  const handleConnect = async () => {
    setIsConnecting(true);
    setError(null);
    setQrCode(null);

    try {
      const res = await api.post("/tenants/me/whatsapp/connect");
      const qrData = res.data.qr_code;

      // UAZAPI returns the QR as a data URI (or raw base64) in `code`.
      if (qrData?.base64) {
        setQrCode(qrData.base64);
      } else if (qrData?.code) {
        setQrCode(qrData.code);
      }

      setInstanceName(res.data.instance);
      setStatus(res.data.status === "connected" ? "connected" : "connecting");
      setIsPolling(res.data.status !== "connected");
    } catch (err: any) {
      const message =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        "Erro ao conectar. Tente novamente em alguns segundos.";
      setError(message);
      setIsConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    setShowDisconnectDialog(false);
    setIsDisconnecting(true);
    setError(null);

    try {
      await api.delete("/tenants/me/whatsapp/disconnect");
      setStatus("disconnected");
      setQrCode(null);
      setInstanceName(null);
    } catch (err: any) {
      const message =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        "Erro ao desconectar.";
      setError(message);
    } finally {
      setIsDisconnecting(false);
    }
  };

  const statusConfig: Record<
    ConnectionStatus,
    { label: string; color: string; icon: React.ReactNode; bg: string }
  > = {
    loading: {
      label: "Verificando...",
      color: "text-muted-foreground",
      icon: <Loader2 className="h-5 w-5 animate-spin" />,
      bg: "bg-muted/30",
    },
    not_configured: {
      label: "Não Configurado",
      color: "text-muted-foreground",
      icon: <WifiOff className="h-5 w-5" />,
      bg: "bg-muted/30",
    },
    connecting: {
      label: "Aguardando Conexão...",
      color: "text-amber-500",
      icon: <Loader2 className="h-5 w-5 animate-spin" />,
      bg: "bg-amber-500/10",
    },
    connected: {
      label: "Conectado",
      color: "text-emerald-500",
      icon: <CheckCircle2 className="h-5 w-5" />,
      bg: "bg-emerald-500/10",
    },
    disconnected: {
      label: "Desconectado",
      color: "text-red-400",
      icon: <WifiOff className="h-5 w-5" />,
      bg: "bg-red-500/10",
    },
    unknown: {
      label: "Status Desconhecido",
      color: "text-muted-foreground",
      icon: <AlertCircle className="h-5 w-5" />,
      bg: "bg-muted/30",
    },
  };

  const current = statusConfig[status];

  return (
    <div className="space-y-8 max-w-2xl bg-background/5">
      <div>
        <h3 className="font-heading text-lg font-bold text-foreground">Conexão WhatsApp</h3>
        <p className="text-xs text-muted-foreground/80 font-sans mt-0.5">
          Conecte o WhatsApp da sua clínica para que a Sofia possa atender seus pacientes automaticamente.
        </p>
      </div>

      {/* Status Card */}
      <div
        className={cn(
          "rounded-2xl border p-4.5 flex items-center gap-4 transition-all shadow-md bg-white/5",
          status === "connected"
            ? "border-emerald-500/20"
            : status === "connecting"
            ? "border-amber-500/20"
            : "border-white/10"
        )}
      >
        <div className={cn("shrink-0", current.color)}>{current.icon}</div>
        <div className="flex-1 min-w-0">
          <p className={cn("font-heading text-sm font-bold", current.color)}>
            {current.label}
          </p>
          {instanceName && (
            <p className="text-xs text-muted-foreground/80 mt-0.5 truncate font-sans">
              Instância: <code className="font-mono bg-white/5 border border-white/5 rounded-md px-1.5 py-0.5 text-[11px] text-foreground">{instanceName}</code>
            </p>
          )}
        </div>
        <div className="shrink-0 flex gap-2">
          {status !== "loading" && (
            <button
              onClick={fetchStatus}
              className="text-muted-foreground hover:text-foreground cursor-pointer rounded-lg hover:bg-white/5 p-1.5 transition-colors"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-2xl border border-red-500/20 bg-red-500/5 p-4 shadow-md">
          <p className="text-xs font-sans font-semibold text-red-400 flex items-center gap-1.5">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
          </p>
        </div>
      )}

      {/* QR Code */}
      {qrCode && status !== "connected" && (
        <div className="flex flex-col items-center gap-4 rounded-2xl border border-white/10 bg-white/5 p-6 shadow-xl">
          <div className="flex items-center gap-2 text-amber-400">
            <QrCode className="h-5 w-5 animate-pulse" />
            <p className="font-heading text-sm font-semibold">Escaneie o QR Code com seu WhatsApp</p>
          </div>
          <div className="bg-white rounded-2xl p-4.5 shadow-2xl">
            <img
              src={qrCode.startsWith("data:") ? qrCode : `data:image/png;base64,${qrCode}`}
              alt="QR Code WhatsApp"
              className="w-64 h-64 object-contain"
            />
          </div>
          <p className="text-xs text-muted-foreground/80 text-center max-w-sm font-sans leading-relaxed">
            Abra o WhatsApp no celular → Menu (⋮) → Aparelhos conectados → Conectar um aparelho → Escaneie o código acima.
          </p>
        </div>
      )}

      {/* Connected state info banner */}
      {status === "connected" && (
        <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-5 shadow-md">
          <div className="flex items-start gap-3">
            <Wifi className="h-5 w-5 text-emerald-400 shrink-0 mt-0.5" />
            <div>
              <p className="font-heading text-sm font-bold text-emerald-400">
                WhatsApp conectado com sucesso!
              </p>
              <p className="text-xs text-muted-foreground/80 mt-1 leading-relaxed font-sans">
                A Sofia está pronta para atender seus pacientes. As mensagens recebidas
                aparecerão automaticamente no <strong>Inbox</strong> e serão respondidas pela IA.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex gap-3 pt-2">
        {(status === "not_configured" ||
          status === "disconnected" ||
          status === "unknown") && (
          <button onClick={handleConnect} disabled={isConnecting} className="sofia-btn-gradient px-5 py-2.5 rounded-xl text-white font-bold text-xs shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center">
            {isConnecting ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <QrCode className="mr-1.5 h-3.5 w-3.5" />
            )}
            Conectar WhatsApp
          </button>
        )}

        {status === "connecting" && !qrCode && (
          <button onClick={handleConnect} disabled={isConnecting} className="sofia-btn-gradient px-5 py-2.5 rounded-xl text-white font-bold text-xs shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center">
            {isConnecting ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
            )}
            Gerar Novo QR Code
          </button>
        )}

        {(status === "connected" || status === "connecting") && (
          <button
            onClick={() => setShowDisconnectDialog(true)}
            disabled={isDisconnecting}
            className="h-10 text-xs rounded-xl px-4 text-destructive border border-destructive/20 bg-destructive/5 hover:bg-destructive/10 transition-all cursor-pointer font-semibold flex items-center gap-1.5"
          >
            {isDisconnecting ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Unplug className="mr-1.5 h-3.5 w-3.5" />
            )}
            Desconectar
          </button>
        )}
      </div>

      {/* Disconnect confirmation dialog */}
      <Dialog open={showDisconnectDialog} onOpenChange={setShowDisconnectDialog}>
        <DialogContent className="sm:max-w-[440px] bg-background/95 border-white/10 backdrop-blur-md rounded-[28px] p-6 shadow-2xl overflow-hidden animate-in fade-in duration-200">
          <DialogHeader className="space-y-1">
            <DialogTitle className="font-heading text-lg font-bold text-foreground">Desconectar WhatsApp?</DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground/80 font-sans mt-0.5">
              A Sofia não poderá mais responder mensagens no WhatsApp enquanto estiver desconectado.
              Você poderá reconectar a qualquer momento.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="pt-4 border-t border-white/10 flex flex-col-reverse sm:flex-row justify-end gap-3 mt-4">
            <button onClick={() => setShowDisconnectDialog(false)} className="px-5 py-2.5 rounded-xl font-semibold text-muted-foreground hover:bg-white/5 hover:text-foreground text-xs transition-all cursor-pointer text-center">
              Cancelar
            </button>
            <button onClick={handleDisconnect} disabled={isDisconnecting} className="h-10 text-xs rounded-xl px-4 bg-destructive text-white hover:brightness-110 shadow-md shadow-destructive/20 transition-all cursor-pointer font-semibold flex items-center justify-center">
              {isDisconnecting && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
              Sim, desconectar
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Behaviour settings */}
      <div className="space-y-3">
        <h4 className="font-heading text-sm font-semibold text-foreground">Comportamento</h4>
        <div className="flex flex-row items-center justify-between rounded-2xl border border-white/10 p-4 bg-white/5 shadow-md">
          <div className="space-y-0.5">
            <Label className="font-heading text-sm font-semibold text-foreground flex items-center gap-2">
              <Users className="h-4 w-4 text-muted-foreground/60" />
              Ignorar mensagens de grupos
            </Label>
            <p className="text-xs text-muted-foreground/80 font-sans mt-0.5 leading-relaxed">
              A Sofia não responde mensagens enviadas em grupos do WhatsApp, apenas conversas individuais.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {isSavingBehaviour && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
            <Switch
              checked={ignoreGroups}
              onCheckedChange={async (checked) => {
                setIgnoreGroups(checked);
                await updateTenant({ settings: { ignore_groups: checked } });
              }}
              disabled={isSavingBehaviour}
              className="cursor-pointer"
            />
          </div>
        </div>
      </div>

      {/* Info box */}
      <div className="rounded-2xl border border-blue-500/20 bg-blue-500/5 p-5 mt-4 shadow-md">
        <h4 className="font-heading text-sm font-semibold text-blue-400 mb-2">
          Como funciona?
        </h4>
        <ol className="text-xs text-muted-foreground/80 space-y-1.5 list-decimal list-inside leading-relaxed font-sans">
          <li>Clique em <strong>"Conectar WhatsApp"</strong> para gerar um QR Code.</li>
          <li>Escaneie o código com o app WhatsApp Business do celular da clínica.</li>
          <li>Quando aparecer <span className="text-emerald-400 font-semibold">●&nbsp;Conectado</span>, a Sofia começa a atender automaticamente.</li>
          <li>As conversas aparecerão no <strong>Inbox</strong> do painel em tempo real.</li>
        </ol>
      </div>
    </div>
  );
}

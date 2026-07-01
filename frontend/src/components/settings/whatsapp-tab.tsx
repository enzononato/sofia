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
    <div className="space-y-8 max-w-2xl">
      <div>
        <h3 className="text-lg font-medium">Conexão WhatsApp</h3>
        <p className="text-sm text-muted-foreground mt-1">
          Conecte o WhatsApp da sua clínica para que a Sofia possa atender seus pacientes automaticamente.
        </p>
      </div>

      {/* Status Card */}
      <div
        className={cn(
          "rounded-xl border p-5 flex items-center gap-4 transition-colors",
          current.bg,
          status === "connected"
            ? "border-emerald-500/30"
            : status === "connecting"
            ? "border-amber-500/30"
            : "border-border/50"
        )}
      >
        <div className={cn("shrink-0", current.color)}>{current.icon}</div>
        <div className="flex-1 min-w-0">
          <p className={cn("text-sm font-semibold", current.color)}>
            {current.label}
          </p>
          {instanceName && (
            <p className="text-xs text-muted-foreground mt-0.5 truncate">
              Instância: <code className="font-mono">{instanceName}</code>
            </p>
          )}
        </div>
        <div className="shrink-0 flex gap-2">
          {status !== "loading" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={fetchStatus}
              className="text-muted-foreground"
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4">
          <p className="text-sm text-red-400">{error}</p>
        </div>
      )}

      {/* QR Code */}
      {qrCode && status === "connecting" && (
        <div className="flex flex-col items-center gap-4 rounded-xl border border-border/50 bg-card/50 p-6">
          <div className="flex items-center gap-2 text-amber-500">
            <QrCode className="h-5 w-5" />
            <p className="text-sm font-medium">Escaneie o QR Code com seu WhatsApp</p>
          </div>
          <div className="bg-white rounded-xl p-4 shadow-md">
            <img
              src={qrCode.startsWith("data:") ? qrCode : `data:image/png;base64,${qrCode}`}
              alt="QR Code WhatsApp"
              className="w-64 h-64 object-contain"
            />
          </div>
          <p className="text-xs text-muted-foreground text-center max-w-sm">
            Abra o WhatsApp no celular → Menu (⋮) → Dispositivos Conectados → Conectar Dispositivo → Escaneie o código acima.
          </p>
        </div>
      )}

      {/* Connected state */}
      {status === "connected" && (
        <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-5">
          <div className="flex items-start gap-3">
            <Wifi className="h-5 w-5 text-emerald-500 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-emerald-500">
                WhatsApp conectado com sucesso!
              </p>
              <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
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
          <Button onClick={handleConnect} disabled={isConnecting}>
            {isConnecting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <QrCode className="mr-2 h-4 w-4" />
            )}
            Conectar WhatsApp
          </Button>
        )}

        {status === "connecting" && !qrCode && (
          <Button onClick={handleConnect} disabled={isConnecting}>
            {isConnecting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="mr-2 h-4 w-4" />
            )}
            Gerar Novo QR Code
          </Button>
        )}

        {(status === "connected" || status === "connecting") && (
          <Button
            variant="outline"
            onClick={() => setShowDisconnectDialog(true)}
            disabled={isDisconnecting}
            className="text-destructive border-destructive/30 hover:bg-destructive/10"
          >
            {isDisconnecting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Unplug className="mr-2 h-4 w-4" />
            )}
            Desconectar
          </Button>
        )}
      </div>

      {/* Disconnect confirmation dialog */}
      <Dialog open={showDisconnectDialog} onOpenChange={setShowDisconnectDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Desconectar WhatsApp?</DialogTitle>
            <DialogDescription>
              A Sofia não poderá mais responder mensagens no WhatsApp enquanto estiver desconectado.
              Você poderá reconectar a qualquer momento.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDisconnectDialog(false)}>
              Cancelar
            </Button>
            <Button variant="destructive" onClick={handleDisconnect} disabled={isDisconnecting}>
              {isDisconnecting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Sim, desconectar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Behaviour settings */}
      <div className="space-y-3">
        <h4 className="text-sm font-semibold">Comportamento</h4>
        <div className="flex flex-row items-center justify-between rounded-lg border border-border/50 p-4 bg-muted/20">
          <div className="space-y-0.5">
            <Label className="text-base flex items-center gap-2">
              <Users className="h-4 w-4 text-muted-foreground" />
              Ignorar mensagens de grupos
            </Label>
            <p className="text-sm text-muted-foreground">
              A Sofia não responde mensagens enviadas em grupos do WhatsApp, apenas conversas individuais.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {isSavingBehaviour && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            <Switch
              checked={ignoreGroups}
              onCheckedChange={async (checked) => {
                setIgnoreGroups(checked);
                await updateTenant({ settings: { ignore_groups: checked } });
              }}
              disabled={isSavingBehaviour}
            />
          </div>
        </div>
      </div>

      {/* Info box */}
      <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 p-4 mt-4">
        <h4 className="text-sm font-semibold text-blue-400 mb-1.5">
          Como funciona?
        </h4>
        <ol className="text-xs text-muted-foreground space-y-1.5 list-decimal list-inside leading-relaxed">
          <li>Clique em <strong>"Conectar WhatsApp"</strong> para gerar um QR Code.</li>
          <li>Escaneie o código com o app WhatsApp Business do celular da clínica.</li>
          <li>Quando aparecer <span className="text-emerald-500 font-medium">●&nbsp;Conectado</span>, a Sofia começa a atender automaticamente.</li>
          <li>As conversas aparecerão no <strong>Inbox</strong> do painel em tempo real.</li>
        </ol>
      </div>
    </div>
  );
}

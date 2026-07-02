"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import {
  User, UserRole, useTeamMembers, useCreateTeamMember, useUpdateTeamMember,
  useInvitations, useInviteUser, useRevokeInvitation,
} from "@/hooks/useTeam";
import { useAuthStore } from "@/store/useAuthStore";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Search, Plus, Loader2, Shield, Mail, Settings2, KeyRound, CalendarClock, Send, Copy, Check, Trash2, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { ProfessionalConfigDialog } from "@/components/team/professional-config-dialog";

// Roles that attend patients → can have services + work hours configured
const ATTENDING_ROLES: UserRole[] = ["professional", "owner"];

const ROLE_LABELS: Record<UserRole, string> = {
  owner: "Proprietário",
  admin: "Administrador",
  receptionist: "Recepcionista",
  professional: "Profissional",
  viewer: "Visualizador",
};

const ROLE_COLORS: Record<UserRole, string> = {
  owner: "bg-purple-500/10 text-purple-600 border-purple-500/20",
  admin: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20",
  receptionist: "bg-blue-500/10 text-blue-600 border-blue-500/20",
  professional: "bg-amber-500/10 text-amber-600 border-amber-500/20",
  viewer: "bg-slate-500/10 text-slate-600 border-slate-500/20",
};

const formSchema = z.object({
  full_name: z.string().min(1, "Nome é obrigatório"),
  email: z.string().email("E-mail inválido"),
  role: z.enum(["owner", "admin", "receptionist", "professional", "viewer"]),
  password: z.string().min(8, "Mínimo de 8 caracteres").optional().or(z.literal("")),
  is_active: z.boolean().default(true),
});

type FormValues = z.infer<typeof formSchema>;

export default function TeamPage() {
  const currentUserRole = useAuthStore(state => state.userRole);
  
  const { data: team, isLoading, isError } = useTeamMembers();
  const { mutateAsync: createMember, isPending: isCreating } = useCreateTeamMember();
  const { mutateAsync: updateMember, isPending: isUpdating } = useUpdateTeamMember();
  const { data: invitations } = useInvitations();
  const { mutateAsync: inviteUser, isPending: isInviting } = useInviteUser();
  const { mutateAsync: revokeInvite } = useRevokeInvitation();

  const [search, setSearch] = useState("");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [configUser, setConfigUser] = useState<User | null>(null);
  const [generatePassword, setGeneratePassword] = useState(false);

  // Invite-by-email state
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<UserRole>("professional");
  const [inviteResult, setInviteResult] = useState<{ link: string; emailSent: boolean } | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const resetInvite = () => {
    setInviteOpen(false);
    setInviteEmail("");
    setInviteRole("professional");
    setInviteResult(null);
    setInviteError(null);
    setCopied(false);
  };

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setInviteError(null);
    try {
      const res = await inviteUser({ email: inviteEmail, role: inviteRole });
      setInviteResult({ link: res.invite_link, emailSent: res.email_sent });
    } catch (err: unknown) {
      const anyErr = err as { response?: { data?: { error?: { message?: string } } } };
      setInviteError(anyErr?.response?.data?.error?.message || "Erro ao enviar o convite.");
    }
  };

  const copyLink = () => {
    if (inviteResult) {
      navigator.clipboard.writeText(inviteResult.link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const { register, handleSubmit, reset, watch, setValue, formState: { errors } } = useForm<FormValues>({
    resolver: zodResolver(formSchema) as any,
    defaultValues: {
      full_name: "",
      email: "",
      role: "receptionist",
      password: "",
      is_active: true,
    },
  });

  const selectedRole = watch("role");

  const openNewModal = () => {
    setEditingUser(null);
    setGeneratePassword(true);
    reset({
      full_name: "",
      email: "",
      role: "receptionist",
      password: crypto.randomUUID().slice(0, 12),
      is_active: true,
    });
    setIsModalOpen(true);
  };

  const openEditModal = (user: User) => {
    // Check permissions
    if (user.role === "owner" && currentUserRole !== "owner") {
      return; // Handled by disabled UI, but double check
    }
    
    setEditingUser(user);
    setGeneratePassword(false);
    reset({
      full_name: user.full_name,
      email: user.email,
      role: user.role,
      password: "", // Optional on edit
      is_active: user.is_active,
    });
    setIsModalOpen(true);
  };

  const handleGeneratePassword = () => {
    setValue("password", crypto.randomUUID().slice(0, 12));
    setGeneratePassword(true);
  };

  const onSubmit = async (data: FormValues) => {
    try {
      if (editingUser) {
        await updateMember({
          id: editingUser.id,
          data: {
            full_name: data.full_name,
            role: data.role,
            is_active: data.is_active,
          }
        });
        setIsModalOpen(false);
      } else {
        const isProfessional = data.role === "professional";
        const created = await createMember({
          email: data.email,
          full_name: data.full_name,
          role: data.role,
          // Professionals can be bookable resources without login — let the
          // server auto-generate a password. Other roles get the shown password.
          password: isProfessional ? undefined : (data.password || undefined),
        });
        setIsModalOpen(false);
        // One flow: for attending roles, jump straight into services + hours.
        if (ATTENDING_ROLES.includes(data.role)) {
          setConfigUser(created);
        }
      }
    } catch (error) {
      console.error("Failed to save user", error);
      alert("Erro ao salvar usuário. Verifique os dados e tente novamente.");
    }
  };

  const filteredTeam = team?.filter(u => 
    u.full_name.toLowerCase().includes(search.toLowerCase()) || 
    u.email.toLowerCase().includes(search.toLowerCase())
  ) || [];

    return (
    <div className="flex flex-col h-full max-w-6xl mx-auto p-4 md:p-8 bg-background/5">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="font-heading text-2xl font-bold tracking-tight text-foreground">Equipe</h1>
          <p className="text-muted-foreground mt-1 text-sm font-sans">
            Gerencie o acesso da sua equipe ao sistema.
          </p>
        </div>
        <div className="flex gap-3 shrink-0">
          <Button variant="outline" onClick={openNewModal} className="h-9 text-xs rounded-full px-4 border-white/10 bg-white/5 hover:bg-white/10 text-muted-foreground hover:text-foreground transition-all cursor-pointer font-semibold">
            <Plus className="mr-1.5 h-4 w-4" /> Adicionar manualmente
          </Button>
          <Button onClick={() => { setInviteResult(null); setInviteError(null); setInviteOpen(true); }} className="h-9 text-xs rounded-full px-4 bg-primary text-primary-foreground hover:brightness-110 shadow-md shadow-primary/20 transition-all cursor-pointer font-semibold">
            <Send className="mr-1.5 h-4 w-4" /> Convidar por e-mail
          </Button>
        </div>
      </div>

      {/* Search Filter */}
      <div className="flex items-center space-x-2 mb-6">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar por nome ou e-mail..."
            className="pl-10 h-10 bg-background/55 border-white/10 focus-visible:border-primary/50 focus-visible:ring-0 rounded-xl placeholder:text-muted-foreground/60 text-sm"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center p-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : isError ? (
        <div className="p-4 border border-destructive/20 bg-destructive/5 text-destructive rounded-xl text-sm font-sans font-medium">
          Erro ao carregar equipe. Verifique sua conexão ou tente recarregar.
        </div>
      ) : filteredTeam.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-12 text-center border border-dashed border-white/10 rounded-2xl bg-white/5 backdrop-blur-sm">
          <UsersIcon className="h-12 w-12 text-muted-foreground/40 mb-4" />
          <h3 className="font-heading text-lg font-semibold text-foreground">Nenhum membro encontrado</h3>
          <p className="text-sm text-muted-foreground mt-1 font-sans">
            {search ? "Tente buscar por outro nome." : "Sua equipe está vazia."}
          </p>
        </div>
      ) : (
        <div className="rounded-2xl border border-white/10 bg-background/45 backdrop-blur-md overflow-hidden shadow-xl">
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="bg-white/5 text-muted-foreground border-b border-white/10">
                <tr>
                  <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider font-mono">Membro</th>
                  <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider font-mono">Status</th>
                  <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider font-mono">Função</th>
                  <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider font-mono">Último Acesso</th>
                  <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider font-mono text-right">Ações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {filteredTeam.map((user) => {
                  const canEdit = currentUserRole === "owner" || (currentUserRole === "admin" && user.role !== "owner");
                  const initials = user.full_name.split(" ").map(n => n[0]).join("").toUpperCase().substring(0, 2);

                  return (
                    <tr key={user.id} className="hover:bg-white/5 transition-colors">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <Avatar className="h-9 w-9 border border-white/10 flex-shrink-0">
                            <AvatarFallback className="bg-primary/5 text-primary text-xs font-mono font-semibold">
                              {initials}
                            </AvatarFallback>
                          </Avatar>
                          <div className="flex flex-col min-w-0">
                            <span className="font-heading font-semibold text-sm text-foreground truncate leading-tight">{user.full_name}</span>
                            <span className="text-xs text-muted-foreground flex items-center gap-1.5 mt-0.5 opacity-80 truncate font-sans">
                              <Mail className="h-3 w-3 text-muted-foreground/60" /> {user.email}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {user.is_active ? (
                          <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-400">
                            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                            Ativo
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground opacity-70">
                            <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/45" />
                            Inativo
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant="outline" className={cn("text-[9px] font-mono uppercase tracking-wider rounded-md", ROLE_COLORS[user.role])}>
                          {ROLE_LABELS[user.role]}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground font-mono">
                        {user.last_login_at 
                          ? format(new Date(user.last_login_at), "dd/MM/yyyy HH:mm")
                          : "Nunca acessou"
                        }
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          {ATTENDING_ROLES.includes(user.role) && (
                            <TooltipProvider>
                              <Tooltip>
                                <TooltipTrigger>
                                  <div>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      onClick={() => setConfigUser(user)}
                                      disabled={!canEdit}
                                      className="h-8 w-8 p-0 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-foreground cursor-pointer disabled:opacity-50"
                                    >
                                      <CalendarClock className="h-4 w-4" />
                                    </Button>
                                  </div>
                                </TooltipTrigger>
                                <TooltipContent className="border-white/10 bg-background/95 text-xs">Serviços e horários de atendimento</TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                          )}
                          <TooltipProvider>
                            <Tooltip>
                              <TooltipTrigger>
                                <div>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => openEditModal(user)}
                                    disabled={!canEdit}
                                    className="h-8 w-8 p-0 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-foreground cursor-pointer disabled:opacity-50"
                                  >
                                    <Settings2 className="h-4 w-4" />
                                  </Button>
                                </div>
                              </TooltipTrigger>
                              {!canEdit && (
                                <TooltipContent className="border-white/10 bg-background/95 text-xs">
                                  Apenas Proprietários podem editar este usuário.
                                </TooltipContent>
                              )}
                            </Tooltip>
                          </TooltipProvider>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {invitations && invitations.length > 0 && (
        <div className="mt-6 rounded-2xl border border-white/10 bg-background/45 backdrop-blur-md p-4 shadow-xl">
          <h3 className="font-heading text-sm font-semibold mb-3 flex items-center gap-2 text-foreground">
            <Clock className="h-4 w-4 text-amber-500 animate-pulse" /> Convites pendentes
          </h3>
          <ul className="divide-y divide-white/5">
            {invitations.map((inv) => (
              <li key={inv.id} className="flex items-center justify-between py-2 text-sm">
                <div className="flex items-center gap-3 min-w-0">
                  <Mail className="h-4 w-4 text-muted-foreground/60 shrink-0" />
                  <span className="truncate text-foreground font-medium">{inv.email}</span>
                  <Badge variant="outline" className={cn("text-[9px] font-mono uppercase tracking-wider rounded-md", ROLE_COLORS[inv.role])}>
                    {ROLE_LABELS[inv.role]}
                  </Badge>
                </div>
                <Button variant="ghost" size="sm" onClick={() => revokeInvite(inv.id)} className="text-destructive hover:bg-destructive/10 hover:text-destructive h-8 px-2 shrink-0 rounded-lg cursor-pointer">
                  <Trash2 className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <ProfessionalConfigDialog
        user={configUser}
        open={!!configUser}
        onOpenChange={(o) => { if (!o) setConfigUser(null); }}
      />

      {/* Invite-by-email dialog */}
      <Dialog open={inviteOpen} onOpenChange={(o) => { if (!o) resetInvite(); }}>
        <DialogContent className="sm:max-w-[440px] bg-background/95 border-white/10 backdrop-blur-md rounded-[28px] p-6 shadow-2xl overflow-hidden animate-in fade-in zoom-in duration-300">
          <DialogHeader className="space-y-1">
            <DialogTitle className="font-heading text-xl font-bold text-foreground">Convidar por e-mail</DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground/80 font-sans mt-1">
              Enviaremos um link de ativação. Se o provedor de e-mail não estiver configurado, você poderá copiar o link e enviar manualmente.
            </DialogDescription>
          </DialogHeader>

          {inviteResult ? (
            <div className="space-y-4 pt-2">
              <div className={cn(
                "rounded-xl p-3 text-xs font-semibold font-sans border",
                inviteResult.emailSent 
                  ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" 
                  : "bg-amber-500/10 text-amber-400 border-amber-500/20",
              )}>
                {inviteResult.emailSent
                  ? "Convite enviado por e-mail com sucesso! 🎉"
                  : "Convite criado. Copie o link abaixo e envie ao membro:"}
              </div>
              <div className="flex gap-2">
                <Input readOnly value={inviteResult.link} className="text-xs h-10 rounded-xl border-white/10 bg-background/55 text-foreground px-3 focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" onFocus={(e) => e.currentTarget.select()} />
                <Button type="button" variant="outline" size="icon" onClick={copyLink} className="h-10 w-10 border-white/10 hover:bg-white/5 cursor-pointer rounded-xl">
                  {copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
                </Button>
              </div>
              <DialogFooter className="pt-2 border-t border-white/10 flex justify-end">
                <button onClick={resetInvite} className="sofia-btn-gradient px-5 py-2.5 rounded-xl text-white font-bold text-xs shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 cursor-pointer text-center">
                  Concluir
                </button>
              </DialogFooter>
            </div>
          ) : (
            <form onSubmit={handleInvite} className="space-y-4 pt-2">
              <div className="space-y-1.5">
                <Label htmlFor="invite_email" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">E-mail</Label>
                <Input id="invite_email" type="email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} required placeholder="profissional@clinica.com" className="h-11 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="invite_role" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Função</Label>
                <select
                  id="invite_role"
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as UserRole)}
                  className="h-11 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full appearance-none bg-[url('data:image/svg+xml,%3Csvg_xmlns=%22http://www.w3.org/2000/svg%22_fill=%22none%22_viewBox=%220_0_24_24%22_stroke=%22%23cbc3d7%22%3E%3Cpath_stroke-linecap=%22round%22_stroke-linejoin=%22round%22_stroke-width=%222%22_d=%22M19_9l-7_7-7-7%22%3E%3C/path%3E%3C/svg%3E')] bg-no-repeat bg-[right_1rem_center] bg-[length:1.25rem]"
                >
                  <option value="professional" className="bg-background text-foreground">Profissional / Médico</option>
                  <option value="receptionist" className="bg-background text-foreground">Recepcionista</option>
                  <option value="viewer" className="bg-background text-foreground">Visualizador</option>
                  <option value="admin" className="bg-background text-foreground">Administrador</option>
                </select>
              </div>
              {inviteError && <p className="text-sm text-destructive font-sans font-medium">{inviteError}</p>}
              <DialogFooter className="pt-4 border-t border-white/10 flex flex-col-reverse sm:flex-row justify-end gap-3 mt-4">
                <button type="button" onClick={resetInvite} className="px-5 py-2.5 rounded-xl font-semibold text-muted-foreground hover:bg-white/5 hover:text-foreground text-xs transition-all cursor-pointer text-center">
                  Cancelar
                </button>
                <button type="submit" disabled={isInviting} className="sofia-btn-gradient px-5 py-2.5 rounded-xl text-white font-bold text-xs shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center">
                  {isInviting && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
                  Enviar convite
                </button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>

      {/* Manual add/edit dialog */}
      <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
        <DialogContent className="sm:max-w-[425px] bg-background/95 border-white/10 backdrop-blur-md rounded-[28px] p-6 shadow-2xl overflow-hidden animate-in fade-in zoom-in duration-300">
          <DialogHeader className="space-y-1">
            <DialogTitle className="font-heading text-xl font-bold text-foreground">{editingUser ? "Editar Membro" : "Convidar Novo Membro"}</DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground/80 font-sans mt-1">
              {editingUser 
                ? "Altere o nível de acesso e status do usuário." 
                : "Convide alguém para a equipe enviando um acesso."}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 pt-4">
            <div className="space-y-1.5">
              <Label htmlFor="full_name" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Nome Completo</Label>
              <Input id="full_name" {...register("full_name")} placeholder="João Silva" className="h-11 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full" />
              {errors.full_name && <p className="text-xs text-destructive font-sans font-medium">{errors.full_name.message as string}</p>}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="email" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">E-mail</Label>
              <Input 
                id="email" 
                type="email" 
                {...register("email")} 
                placeholder="joao@clinica.com" 
                disabled={!!editingUser} 
                className={cn("h-11 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full", editingUser && "bg-white/5 cursor-not-allowed text-muted-foreground")}
              />
              {errors.email && <p className="text-xs text-destructive font-sans font-medium">{errors.email.message as string}</p>}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="role" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Nível de Acesso (Função)</Label>
              <select
                id="role"
                {...register("role")}
                className="h-11 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full appearance-none bg-[url('data:image/svg+xml,%3Csvg_xmlns=%22http://www.w3.org/2000/svg%22_fill=%22none%22_viewBox=%220_0_24_24%22_stroke=%22%23cbc3d7%22%3E%3Cpath_stroke-linecap=%22round%22_stroke-linejoin=%22round%22_stroke-width=%222%22_d=%22M19_9l-7_7-7-7%22%3E%3C/path%3E%3C/svg%3E')] bg-no-repeat bg-[right_1rem_center] bg-[length:1.25rem]"
              >
                <option value="receptionist" className="bg-background text-foreground">Recepcionista</option>
                <option value="professional" className="bg-background text-foreground">Profissional / Médico</option>
                <option value="viewer" className="bg-background text-foreground">Visualizador</option>
                <option value="admin" className="bg-background text-foreground">Administrador</option>
                {currentUserRole === "owner" && <option value="owner" className="bg-background text-foreground">Proprietário</option>}
              </select>
              {selectedRole === "owner" && currentUserRole !== "owner" && (
                <p className="text-xs text-amber-400 flex items-center gap-1.5 mt-1.5 font-sans">
                  <Shield className="h-3.5 w-3.5 text-amber-500" /> Apenas proprietários podem criar proprietários.
                </p>
              )}
            </div>

            {!editingUser && selectedRole !== "professional" && (
              <div className="space-y-1.5 pt-2 border-t border-white/10">
                <div className="flex items-center justify-between mb-1">
                  <Label htmlFor="password" className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/80 block">Senha de Acesso</Label>
                  <button
                    type="button"
                    onClick={handleGeneratePassword}
                    className="text-xs text-primary hover:underline flex items-center gap-1 cursor-pointer font-semibold font-sans"
                  >
                    <KeyRound className="h-3 w-3" /> Gerar automática
                  </button>
                </div>
                <Input
                  id="password"
                  type={generatePassword ? "text" : "password"}
                  {...register("password")}
                  placeholder="Mínimo 8 caracteres"
                  className="h-11 rounded-xl border-white/10 bg-background/55 text-foreground px-4 text-sm focus-visible:ring-1 focus-visible:ring-primary/50 focus:border-primary/50 transition-all w-full"
                />
                {errors.password && <p className="text-xs text-destructive font-sans font-medium">{errors.password.message as string}</p>}
                {generatePassword && (
                  <p className="text-xs text-muted-foreground/80 mt-1 font-sans">
                    Copie e envie esta senha provisória para o membro.
                  </p>
                )}
              </div>
            )}

            {!editingUser && selectedRole === "professional" && (
              <div className="flex items-start gap-2.5 pt-3 border-t border-white/10 text-xs text-muted-foreground font-sans">
                <CalendarClock className="h-4 w-4 mt-0.5 shrink-0 text-amber-500 animate-pulse" />
                <p className="leading-relaxed">
                  Profissionais não precisam de senha de acesso. Após salvar, você
                  define os <strong>serviços</strong> e <strong>horários de atendimento</strong>
                  {" "}(que a Sofia usa para agendar).
                </p>
              </div>
            )}

            {editingUser && (
              <div className="flex items-center justify-between p-3.5 border border-white/10 rounded-2xl bg-white/5">
                <div className="space-y-0.5">
                  <Label className="font-heading text-sm font-semibold text-foreground">Acesso Ativo</Label>
                  <p className="text-xs text-muted-foreground opacity-80 font-sans">Desative para bloquear o acesso do usuário.</p>
                </div>
                <input 
                  type="checkbox" 
                  {...register("is_active")} 
                  className="h-4.5 w-4.5 rounded border-white/10 text-primary focus:ring-primary bg-background/50 accent-primary cursor-pointer"
                />
              </div>
            )}

            <DialogFooter className="pt-4 border-t border-white/10 flex flex-col-reverse sm:flex-row justify-end gap-3 mt-4">
              <button type="button" onClick={() => setIsModalOpen(false)} className="px-5 py-2.5 rounded-xl font-semibold text-muted-foreground hover:bg-white/5 hover:text-foreground text-xs transition-all cursor-pointer text-center">
                Cancelar
              </button>
              <button 
                type="submit" 
                disabled={isCreating || isUpdating || (selectedRole === "owner" && currentUserRole !== "owner")}
                className="sofia-btn-gradient px-5 py-2.5 rounded-xl text-white font-bold text-xs shadow-md shadow-primary/20 hover:brightness-110 active:scale-95 flex items-center justify-center gap-1.5 cursor-pointer text-center disabled:opacity-50"
              >
                {(isCreating || isUpdating) && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
                {editingUser ? "Salvar Alterações" : "Convidar Membro"}
              </button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function UsersIcon(props: any) {
  return (
    <svg
      {...props}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  )
}

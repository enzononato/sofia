"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { User, UserRole, useTeamMembers, useCreateTeamMember, useUpdateTeamMember } from "@/hooks/useTeam";
import { useAuthStore } from "@/store/useAuthStore";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { Search, Plus, Loader2, Shield, User as UserIcon, Mail, Settings2, KeyRound } from "lucide-react";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";

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
  password: z.string().min(6, "Mínimo de 6 caracteres").optional().or(z.literal("")),
  is_active: z.boolean().default(true),
});

type FormValues = z.infer<typeof formSchema>;

export default function TeamPage() {
  const currentUserRole = useAuthStore(state => state.userRole);
  
  const { data: team, isLoading, isError } = useTeamMembers();
  const { mutateAsync: createMember, isPending: isCreating } = useCreateTeamMember();
  const { mutateAsync: updateMember, isPending: isUpdating } = useUpdateTeamMember();

  const [search, setSearch] = useState("");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [generatePassword, setGeneratePassword] = useState(false);

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
      } else {
        await createMember({
          email: data.email,
          full_name: data.full_name,
          role: data.role,
          password: data.password || crypto.randomUUID().slice(0, 12),
        });
      }
      setIsModalOpen(false);
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
    <div className="flex flex-col h-full max-w-6xl mx-auto p-4 md:p-8">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Equipe</h1>
          <p className="text-muted-foreground mt-1">
            Gerencie o acesso da sua equipe ao sistema.
          </p>
        </div>
        <Button onClick={openNewModal} className="shrink-0">
          <Plus className="mr-2 h-4 w-4" /> Convidar Membro
        </Button>
      </div>

      <div className="flex items-center space-x-2 mb-6">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar por nome ou e-mail..."
            className="pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center p-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : isError ? (
        <div className="p-4 border border-destructive/50 bg-destructive/5 text-destructive rounded-lg">
          Erro ao carregar equipe. Verifique sua conexão.
        </div>
      ) : filteredTeam.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-12 text-center border border-dashed rounded-xl bg-card/50">
          <UsersIcon className="h-12 w-12 text-muted-foreground/50 mb-4" />
          <h3 className="text-lg font-medium">Nenhum membro encontrado</h3>
          <p className="text-sm text-muted-foreground mt-1">
            {search ? "Tente buscar por outro nome." : "Sua equipe está vazia."}
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-border/50 bg-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="bg-muted/50 text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 font-medium">Membro</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Função</th>
                  <th className="px-4 py-3 font-medium">Último Acesso</th>
                  <th className="px-4 py-3 font-medium text-right">Ações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {filteredTeam.map((user) => {
                  const canEdit = currentUserRole === "owner" || (currentUserRole === "admin" && user.role !== "owner");
                  const initials = user.full_name.split(" ").map(n => n[0]).join("").toUpperCase().substring(0, 2);

                  return (
                    <tr key={user.id} className="hover:bg-muted/20 transition-colors">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <Avatar className="h-9 w-9 border border-border/50">
                            <AvatarFallback className="bg-primary/5 text-primary text-xs">
                              {initials}
                            </AvatarFallback>
                          </Avatar>
                          <div className="flex flex-col">
                            <span className="font-medium text-foreground">{user.full_name}</span>
                            <span className="text-xs text-muted-foreground flex items-center gap-1">
                              <Mail className="h-3 w-3" /> {user.email}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {user.is_active ? (
                          <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                            <div className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                            Ativo
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                            <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground/50" />
                            Inativo
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant="outline" className={ROLE_COLORS[user.role]}>
                          {ROLE_LABELS[user.role]}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {user.last_login_at 
                          ? format(new Date(user.last_login_at), "dd/MM/yyyy HH:mm", { locale: ptBR })
                          : "Nunca acessou"
                        }
                      </td>
                      <td className="px-4 py-3 text-right">
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger>
                              <div>
                                <Button 
                                  variant="ghost" 
                                  size="sm" 
                                  onClick={() => openEditModal(user)}
                                  disabled={!canEdit}
                                  className="h-8 px-2"
                                >
                                  <Settings2 className="h-4 w-4" />
                                </Button>
                              </div>
                            </TooltipTrigger>
                            {!canEdit && (
                              <TooltipContent>
                                Apenas Proprietários podem editar este usuário.
                              </TooltipContent>
                            )}
                          </Tooltip>
                        </TooltipProvider>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{editingUser ? "Editar Membro" : "Convidar Novo Membro"}</DialogTitle>
            <DialogDescription>
              {editingUser 
                ? "Altere o nível de acesso e status do usuário." 
                : "Convide alguém para a equipe enviando um acesso."}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 pt-4">
            <div className="space-y-2">
              <Label htmlFor="full_name">Nome Completo</Label>
              <Input id="full_name" {...register("full_name")} placeholder="João Silva" />
              {errors.full_name && <p className="text-sm text-destructive">{errors.full_name.message}</p>}
            </div>

            <div className="space-y-2">
              <Label htmlFor="email">E-mail</Label>
              <Input 
                id="email" 
                type="email" 
                {...register("email")} 
                placeholder="joao@clinica.com" 
                disabled={!!editingUser} 
                className={editingUser ? "bg-muted/50 cursor-not-allowed" : ""}
              />
              {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
            </div>

            <div className="space-y-2">
              <Label htmlFor="role">Nível de Acesso (Função)</Label>
              <select
                id="role"
                {...register("role")}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <option value="receptionist">Recepcionista</option>
                <option value="professional">Profissional / Médico</option>
                <option value="viewer">Visualizador</option>
                <option value="admin">Administrador</option>
                {currentUserRole === "owner" && <option value="owner">Proprietário</option>}
              </select>
              {selectedRole === "owner" && currentUserRole !== "owner" && (
                <p className="text-xs text-amber-500 flex items-center gap-1 mt-1">
                  <Shield className="h-3 w-3" /> Apenas proprietários podem criar proprietários.
                </p>
              )}
            </div>

            {!editingUser && (
              <div className="space-y-2 pt-2 border-t border-border/50">
                <div className="flex items-center justify-between">
                  <Label htmlFor="password">Senha de Acesso</Label>
                  <button 
                    type="button" 
                    onClick={handleGeneratePassword}
                    className="text-xs text-primary hover:underline flex items-center gap-1"
                  >
                    <KeyRound className="h-3 w-3" /> Gerar automática
                  </button>
                </div>
                <Input 
                  id="password" 
                  type={generatePassword ? "text" : "password"} 
                  {...register("password")} 
                  placeholder="Mínimo 6 caracteres" 
                />
                {errors.password && <p className="text-xs text-destructive">{errors.password.message}</p>}
                {generatePassword && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Copie e envie esta senha provisória para o membro.
                  </p>
                )}
              </div>
            )}

            {editingUser && (
              <div className="flex items-center justify-between p-3 border border-border/50 rounded-lg bg-muted/20">
                <div className="space-y-0.5">
                  <Label className="text-base">Acesso Ativo</Label>
                  <p className="text-xs text-muted-foreground">Desative para bloquear o acesso do usuário.</p>
                </div>
                <input 
                  type="checkbox" 
                  {...register("is_active")} 
                  className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
                />
              </div>
            )}

            <DialogFooter className="pt-4">
              <Button type="button" variant="outline" onClick={() => setIsModalOpen(false)}>
                Cancelar
              </Button>
              <Button 
                type="submit" 
                disabled={isCreating || isUpdating || (selectedRole === "owner" && currentUserRole !== "owner")}
              >
                {(isCreating || isUpdating) && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {editingUser ? "Salvar Alterações" : "Convidar Membro"}
              </Button>
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

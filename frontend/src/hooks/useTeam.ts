import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/axios";

export type UserRole = "owner" | "admin" | "receptionist" | "professional" | "viewer";

export interface User {
  id: string;
  tenant_id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  last_login_at?: string;
  created_at: string;
}

interface Page<T> {
  data: T[];
  meta: {
    total: number;
    limit: number;
    offset: number;
  };
}

export interface UserCreate {
  email: string;
  full_name: string;
  role: UserRole;
  password?: string;
}

export interface UserUpdate {
  full_name?: string;
  role?: UserRole;
  is_active?: boolean;
}

export interface WorkHourBlock {
  weekday: number; // ISO: 1=Mon … 7=Sun
  start_time: string; // "HH:MM" / "HH:MM:SS"
  end_time: string;
}

export interface UserDetail extends User {
  service_ids: string[];
  work_hours: WorkHourBlock[];
}

export function useTeamMembers() {
  return useQuery({
    queryKey: ["team"],
    queryFn: async () => {
      const response = await api.get<Page<User>>("/users", {
        params: { limit: 100, include_inactive: true }
      });
      return response.data.data;
    },
    staleTime: 5 * 60 * 1000,
  });
}

export function useCreateTeamMember() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: UserCreate) => {
      const response = await api.post<User>("/users", data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["team"] });
    },
  });
}

export function useUpdateTeamMember() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: UserUpdate }) => {
      const response = await api.patch<User>(`/users/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["team"] });
    },
  });
}

// ── Invitations (invite by email) ────────────────────────────────────────────

export interface Invitation {
  id: string;
  email: string;
  role: UserRole;
  expires_at: string;
  accepted_at?: string | null;
  created_at: string;
}

export interface InviteResponse {
  invitation: Invitation;
  invite_link: string;
  email_sent: boolean;
}

export function useInvitations() {
  return useQuery({
    queryKey: ["invitations"],
    queryFn: async () => (await api.get<Invitation[]>("/users/invitations")).data,
    staleTime: 30 * 1000,
  });
}

export function useInviteUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: { email: string; role: UserRole }) =>
      (await api.post<InviteResponse>("/users/invite", data)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["invitations"] }),
  });
}

export function useRevokeInvitation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => { await api.delete(`/users/invitations/${id}`); },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["invitations"] }),
  });
}

// ── Professional config: services offered + work hours (Fase 2) ──────────────

export function useUserDetail(id?: string) {
  return useQuery({
    queryKey: ["user-detail", id],
    queryFn: async () => {
      const response = await api.get<UserDetail>(`/users/${id}`);
      return response.data;
    },
    enabled: !!id,
    staleTime: 0,
  });
}

export function useSetUserServices() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, service_ids }: { id: string; service_ids: string[] }) => {
      const response = await api.put<UserDetail>(`/users/${id}/services`, { service_ids });
      return response.data;
    },
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["user-detail", vars.id] });
      queryClient.invalidateQueries({ queryKey: ["team"] });
    },
  });
}

export function useSetUserWorkHours() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, blocks }: { id: string; blocks: WorkHourBlock[] }) => {
      const response = await api.put<UserDetail>(`/users/${id}/work-hours`, { blocks });
      return response.data;
    },
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["user-detail", vars.id] });
    },
  });
}

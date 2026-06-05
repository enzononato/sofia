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

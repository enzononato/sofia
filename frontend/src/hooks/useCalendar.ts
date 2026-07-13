import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import api from "@/lib/axios";

export interface Service {
  id: string;
  tenant_id: string;
  name: string;
  description?: string | null;
  duration_minutes: number;
  price?: number | null;
  is_active: boolean;
}

export type ServiceCreate = Omit<Service, "id" | "tenant_id" | "is_active">;
export type ServiceUpdate = Partial<ServiceCreate> & { is_active?: boolean };

export interface Appointment {
  id: string;
  tenant_id: string;
  contact_id: string;
  service_id: string | null;
  professional_id: string | null;
  scheduled_at: string;
  ends_at: string | null;
  status: "scheduled" | "confirmed" | "in_progress" | "completed" | "cancelled" | "no_show";
  notes: string | null;
  cancellation_reason: string | null;
}

interface Page<T> {
  data: T[];
  meta: {
    total: number;
    limit: number;
    offset: number;
  };
}

export type AppointmentStatus = Appointment["status"];

export interface AppointmentInput {
  contact_id: string;
  service_id?: string | null;
  professional_id?: string | null;
  scheduled_at: string; // ISO 8601 with timezone
  ends_at?: string | null;
  notes?: string | null;
  status?: AppointmentStatus;
  cancellation_reason?: string | null;
}

export function useCreateAppointment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: AppointmentInput) => {
      const res = await api.post<Appointment>("/appointments", data);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["appointments"] });
      queryClient.invalidateQueries({ queryKey: ["contacts"] }); // CRM stage may advance
    },
  });
}

export function useUpdateAppointment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: Partial<AppointmentInput> }) => {
      const res = await api.patch<Appointment>(`/appointments/${id}`, data);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["appointments"] });
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
    },
  });
}

export function useAppointments(dateFrom: string, dateTo: string, professionalId?: string) {
  return useQuery({
    queryKey: ["appointments", dateFrom, dateTo, professionalId],
    queryFn: async () => {
      // The API expects date_from and date_to as query params
      const response = await api.get<Page<Appointment>>("/appointments", {
        params: {
          date_from: dateFrom,
          date_to: dateTo,
          limit: 100, // Reasonable limit for a single day
          ...(professionalId ? { professional_id: professionalId } : {}),
        },
      });
      return response.data.data;
    },
    staleTime: 60 * 1000,
    placeholderData: keepPreviousData, // Keep old data visible while new day loads
  });
}

export function useServices() {
  return useQuery({
    queryKey: ["services"],
    queryFn: async () => {
      // Assuming a GET /api/v1/services endpoint exists returning list or page
      // Usually services list is small. 
      // Need to handle both Array or Page response just in case
      const response = await api.get("/services");
      if (response.data && Array.isArray(response.data.data)) {
        return response.data.data as Service[];
      }
      return response.data as Service[];
    },
    staleTime: 5 * 60 * 1000, // Services don't change often
  });
}

export function useCreateService() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: ServiceCreate) => {
      const response = await api.post<Service>("/services", data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["services"] });
    },
  });
}

export function useUpdateService() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: ServiceUpdate }) => {
      const response = await api.patch<Service>(`/services/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["services"] });
    },
  });
}

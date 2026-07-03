import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/axios";

export interface TenantSettings {
  whatsapp?: {
    // Secrets (webhook_secret, provider keys) are never returned by the API.
    instance?: string;
    status?: string;
  };
  schedule?: {
    timezone?: string;
    working_days?: number[];
    open_time?: string;
    close_time?: string;
    lunch_start?: string;
    lunch_end?: string;
    slot_granularity_minutes?: number;
  };
  clinic?: {
    address?: string;
    phone?: string;
    email?: string;
    instagram?: string;
    payment_methods?: string[];
    additional_info?: string;
  };
  followups?: {
    reminders_enabled?: boolean;
    reminder_hours?: number[];
    reengagement_enabled?: boolean;
    reengage_after_days?: number;
    reengage_cooldown_days?: number;
  };
  ignore_groups?: boolean;
}

export interface TenantAIConfig {
  model?: string;
  system_prompt?: string;
  temperature?: number;
  max_output_tokens?: number;
  multimodal_enabled?: boolean;
  // "capacity": clinic-wide slots (N simultaneous). "per_professional": each
  // booking is assigned to a professional, respecting their services + hours.
  scheduling_mode?: "capacity" | "per_professional";
  prompt_first_contact?: string;
  prompt_imminent_appointment?: string;
  prompt_post_appointment?: string;
  prompt_active_patient?: string;
  prompt_returning_lead?: string;
  prompt_reactivation?: string;
}

export interface TenantProfile {
  id: string;
  name: string;
  slug: string;
  email: string;
  phone: string | null;
  address: string | null;
  plan: string;
  is_active: boolean;
  ai_config: TenantAIConfig | null;
  settings: TenantSettings | null;
}

export interface TenantUpdatePayload {
  name?: string;
  email?: string;
  phone?: string | null;
  address?: string | null;
  ai_config?: TenantAIConfig;
  settings?: TenantSettings;
}

export function useTenantProfile() {
  return useQuery({
    queryKey: ["tenantProfile"],
    queryFn: async () => {
      const response = await api.get<TenantProfile>("/tenants/me");
      return response.data;
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useUpdateTenant() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: TenantUpdatePayload) => {
      const response = await api.patch<TenantProfile>("/tenants/me", payload);
      return response.data;
    },
    onSuccess: (data) => {
      // Update cache with new data
      queryClient.setQueryData(["tenantProfile"], data);
    },
  });
}

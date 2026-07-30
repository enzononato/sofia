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
    /** Max credit-card installments Sofia may quote. Unset = arranged at the clinic. */
    max_installments?: number;
    /** Evaluation/consultation pricing policy. Unset = Sofia won't claim free or paid. */
    evaluation_fee_mode?: "free" | "paid";
    evaluation_fee?: number;
    evaluation_fee_deductible?: boolean;
    additional_info?: string;
  };
  followups?: {
    reminders_enabled?: boolean;
    reminder_hours?: number[];
    reengagement_enabled?: boolean;
    reengage_after_days?: number;
    reengage_cooldown_days?: number;
    /** E-mail alert to the clinic when Sofia hands a conversation off to a
     * human (fresh handoff + "still waiting" follow-up). Default true. */
    handoff_alert_email_enabled?: boolean;
  };
  ignore_groups?: boolean;
}

// Sofia's personality/behavior (base prompt + per-stage overlays) is fixed in
// code — not tenant-configurable. Only technical AI parameters live here.
export interface TenantAIConfig {
  model?: string;
  temperature?: number;
  max_output_tokens?: number;
  multimodal_enabled?: boolean;
  // Opt-in per clinic: routes each turn to a Booking/Sales specialist instead of
  // the single-agent path. Costs 2-3 Gemini calls per message; default off.
  multi_agent_enabled?: boolean;
  // "capacity": clinic-wide slots (N simultaneous). "per_professional": each
  // booking is assigned to a professional, respecting their services + hours.
  scheduling_mode?: "capacity" | "per_professional";
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

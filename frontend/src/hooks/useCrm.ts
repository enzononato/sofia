import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/axios";

export type CrmStage =
  | "new_lead"
  | "cold_lead"
  | "hot_lead"
  | "scheduled"
  | "attended"
  | "post_care"
  | "lost";

export interface CrmLastMessage {
  content: string;
  created_at: string;
  media_type?: "audio" | "image" | "video" | "document" | null;
}

export interface CrmContact {
  id: string;
  full_name: string;
  whatsapp_name?: string | null;
  profile_picture_url?: string | null;
  phone: string | null;
  status: string;
  crm_stage: CrmStage;
  crm_stage_source?: string | null;
  last_message?: CrmLastMessage | null;
}

export function useCrmContacts() {
  return useQuery({
    queryKey: ["contacts", "crm"],
    queryFn: async () => {
      const res = await api.get<{ data: CrmContact[]; meta: unknown }>("/contacts", {
        params: { limit: 200 },
      });
      return res.data.data;
    },
    staleTime: 30 * 1000,
  });
}

// Move a contact between CRM columns with optimistic UI. A manual move marks
// crm_stage_source="manual" on the backend so the AI won't auto-regress it.
export function useMoveCrmStage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, crm_stage }: { id: string; crm_stage: CrmStage }) => {
      const res = await api.patch(`/contacts/${id}`, { crm_stage });
      return res.data;
    },
    onMutate: async ({ id, crm_stage }) => {
      await queryClient.cancelQueries({ queryKey: ["contacts", "crm"] });
      const prev = queryClient.getQueryData<CrmContact[]>(["contacts", "crm"]);
      if (prev) {
        queryClient.setQueryData<CrmContact[]>(
          ["contacts", "crm"],
          prev.map((c) => (c.id === id ? { ...c, crm_stage } : c)),
        );
      }
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(["contacts", "crm"], ctx.prev);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["contacts", "crm"] });
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
    },
  });
}

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/axios";
import { CrmStage } from "@/hooks/useCrm";

export interface PatientLastMessage {
  content: string;
  created_at: string;
  media_type?: "audio" | "image" | "video" | "document" | null;
}

export interface Patient {
  id: string;
  full_name: string;
  whatsapp_name?: string | null;
  profile_picture_url?: string | null;
  phone: string | null;
  email?: string | null;
  address?: string | null;
  status: string;
  crm_stage: CrmStage;
  crm_stage_source?: string | null;
  crm_stage_updated_at?: string | null;
  last_inbound_at?: string | null;
  ai_paused: boolean;
  created_at: string;
  updated_at: string;
  last_message?: PatientLastMessage | null;
}

interface PatientsPage {
  data: Patient[];
  meta: { total: number; limit: number; offset: number };
}

// NOTE: `/contacts` filters server-side by `search` (name/phone ilike) and by
// `status` (ContactStatus: lead/active/inactive/blocked) — it has NO query
// param for `crm_stage` (the Kanban pipeline stage). The Patients page filters
// by crm_stage client-side over the fetched page, the same pattern already
// used by useCrmContacts + KanbanBoard for the CRM view.
export function usePatients({ search, status }: { search?: string; status?: string }) {
  return useQuery({
    queryKey: ["contacts", "patients", search, status],
    queryFn: async () => {
      const res = await api.get<PatientsPage>("/contacts", {
        params: {
          search: search || undefined,
          status: status || undefined,
          limit: 100,
        },
      });
      return res.data.data;
    },
    staleTime: 30 * 1000,
  });
}

export interface PatientUpdateInput {
  full_name?: string;
  email?: string | null;
  phone?: string | null;
  address?: string | null;
}

export function useUpdatePatient() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: PatientUpdateInput }) => {
      const res = await api.patch<Patient>(`/contacts/${id}`, data);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contacts", "patients"] });
      // Inbox/CRM also read `/contacts` — keep them in sync too.
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
    },
  });
}

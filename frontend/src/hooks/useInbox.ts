import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/axios";

// Typings based on the python schemas
export interface Message {
  id: string;
  tenant_id: string;
  contact_id: string;
  direction: "INBOUND" | "OUTBOUND";
  channel: string;
  content: string;
  ai_model_used?: string | null;
  created_at: string;
  // Multimodal — media_url holds the data URI when this message is media
  media_type?: "audio" | "image" | "video" | "document" | null;
  media_mime_type?: string | null;
  media_size_bytes?: number | null;
  media_url?: string | null;
}

export interface Contact {
  id: string;
  full_name: string;
  whatsapp_name?: string | null;
  profile_picture_url?: string | null;
  ai_paused: boolean;
  phone: string;
  status: string;
  last_message?: Message;
}

export function useContacts() {
  return useQuery({
    queryKey: ["contacts"],
    queryFn: async () => {
      const response = await api.get<{ data: Contact[], meta: any }>("/contacts");
      return response.data.data;
    },
    staleTime: 5 * 1000,
    refetchInterval: 10 * 1000,
    refetchIntervalInBackground: false,
  });
}

export function useMessages(contactId: string | null) {
  return useQuery({
    queryKey: ["messages", contactId],
    queryFn: async () => {
      if (!contactId) return [];
      const response = await api.get<{ data: Message[], meta: any }>(`/contacts/${contactId}/messages`);
      return response.data.data;
    },
    enabled: !!contactId,
    staleTime: 3 * 1000,
    refetchInterval: 5 * 1000,
    refetchIntervalInBackground: false,
  });
}

export function useSendMessage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ contactId, content }: { contactId: string; content: string }) => {
      const response = await api.post(`/contacts/${contactId}/messages`, {
        content,
        direction: "outbound",
        channel: "whatsapp"
      });
      return response.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["messages", variables.contactId] });
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
    },
  });
}

export function useSendMedia() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({
      contactId,
      media_type,
      media,
      caption,
      file_name,
    }: {
      contactId: string;
      media_type: "audio" | "image" | "document";
      media: string;
      caption?: string;
      file_name?: string;
    }) => {
      const response = await api.post(`/contacts/${contactId}/messages/media`, {
        media_type,
        media,
        caption,
        file_name,
      });
      return response.data;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["messages", variables.contactId] });
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
    },
  });
}

export function useUpdateContact() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: Partial<Contact> }) => {
      const response = await api.patch(`/contacts/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
    },
  });
}

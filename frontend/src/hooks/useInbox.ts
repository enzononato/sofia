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

// GET /contacts (listing) sends a lightweight preview — no `media_url` — so
// the Inbox sidebar doesn't pull multi-MB base64 payloads for every contact.
// The full `Message` (with `media_url`) is only ever returned by
// GET /contacts/{id}/messages, for the currently open conversation.
export interface MessagePreview {
  id: string;
  tenant_id: string;
  contact_id: string;
  direction: "INBOUND" | "OUTBOUND";
  channel: string;
  content: string;
  ai_model_used?: string | null;
  created_at: string;
  media_type?: "audio" | "image" | "video" | "document" | null;
}

export interface Contact {
  id: string;
  full_name: string;
  whatsapp_name?: string | null;
  profile_picture_url?: string | null;
  ai_paused: boolean;
  phone: string;
  status: string;
  last_message?: MessagePreview;
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

// Polling window for the open conversation. Every tick re-fetches this many
// most-recent messages (backend returns newest-first, we reverse for the UI)
// — capped well below the page default (50) since the open chat only needs
// enough recent context to feel live, not the whole thread every 8s. Media
// messages in this window still carry their full `media_url` (the Inbox needs
// to actually play/render them), so this is the main lever against re-pulling
// several MB of base64 audio/images on every poll tick without touching the
// initial full-history load a user gets by scrolling up (still served via the
// same endpoint's default `limit`, just not part of the recurring poll below).
const MESSAGES_POLL_LIMIT = 25;

export function useMessages(contactId: string | null) {
  return useQuery({
    queryKey: ["messages", contactId],
    queryFn: async () => {
      if (!contactId) return [];
      const response = await api.get<{ data: Message[], meta: any }>(
        `/contacts/${contactId}/messages`,
        { params: { limit: MESSAGES_POLL_LIMIT } }
      );
      return response.data.data;
    },
    enabled: !!contactId,
    // Was 3s/5s — widened moderately to cut redundant re-fetches of the whole
    // (media-bearing) page while the conversation is idle; still feels
    // near-real-time for an active chat. See CLAUDE.md Batch 2B notes: a
    // dedicated incremental (`created_after`) fetch or a media-on-demand
    // endpoint would cut this further but is deliberately out of scope here.
    staleTime: 6 * 1000,
    refetchInterval: 9 * 1000,
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

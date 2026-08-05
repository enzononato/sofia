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
  // Set when someone on the team replied to this patient straight from their
  // own phone / WhatsApp Web: Sofia stays quiet until it lapses (60 min,
  // renewed on each hand-typed message). Distinct from `ai_paused`, which only
  // staff clear. Read-only — the API never accepts it on a PATCH.
  human_takeover_until?: string | null;
  phone: string;
  status: string;
  last_message?: MessagePreview;
}

/** True while a staff member is handling this conversation by hand. */
export function isInHumanTakeover(contact: Pick<Contact, "human_takeover_until">): boolean {
  if (!contact.human_takeover_until) return false;
  return new Date(contact.human_takeover_until).getTime() > Date.now();
}

export function useContacts() {
  return useQuery({
    queryKey: ["contacts"],
    queryFn: async () => {
      const response = await api.get<{ data: Contact[], meta: any }>("/contacts");
      return response.data.data;
    },
    // Wave 4: SSE (see useInboxEvents) now invalidates this query the instant
    // a real event happens — this interval is a permanent safety net (not
    // gated on "is SSE healthy"), which is why it can be this much longer
    // than before (was 5s/10s).
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
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
    // Wave 4: widened again (was 6s/9s) now that SSE (useInboxEvents)
    // invalidates this query instantly on a real new message — this interval
    // is a permanent safety net, not the primary update path, so it can
    // afford to be long. See CLAUDE.md Batch 2B notes for the earlier
    // media-payload rationale (still applies): a dedicated incremental
    // (`created_after`) fetch or a media-on-demand endpoint would cut this
    // further but is deliberately out of scope here.
    staleTime: 30 * 1000,
    refetchInterval: 45 * 1000,
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

// Staff copilot: ask Sofia to DRAFT a reply for the currently open
// conversation. Read-only on the backend (never sends/persists/books) — the
// caller drops the returned text into the message input for the human to edit
// and send. See POST /contacts/{id}/suggest-reply.
export function useSuggestReply() {
  return useMutation({
    mutationFn: async (contactId: string) => {
      const response = await api.post<{ suggestion: string }>(
        `/contacts/${contactId}/suggest-reply`
      );
      return response.data.suggestion;
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

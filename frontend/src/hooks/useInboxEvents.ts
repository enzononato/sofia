"use client";

/**
 * Real-time Inbox updates via Server-Sent Events (Wave 4). Mounted once by
 * InboxLayout (the single component that owns both ContactList and
 * ChatWindow) — not per-child-component, so there's exactly one open
 * connection per Inbox session.
 *
 * Native EventSource can't send custom headers (no Authorization, no
 * X-Tenant-ID), so auth rides in a short-lived `?ticket=` query param minted
 * via POST /events/ticket (a normal, header-authenticated call through the
 * `api` axios instance) instead of the 30-min access token.
 *
 * This is a pure latency optimization layered on top of the permanent
 * polling safety net in useInbox.ts (useContacts/useMessages) — there is
 * deliberately no "is SSE healthy" flag gating that polling. If SSE keeps
 * failing to (re)connect, this hook simply gives up after a few retries for
 * the rest of the session; the UI still updates, just on the polling
 * interval instead of instantly.
 */

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import api, { API_BASE_URL } from "@/lib/axios";

const MAX_RETRIES = 5;
const RETRY_BACKOFF_MS = 2000;

interface InboxRealtimeEvent {
  type: "message" | "contact_updated";
  contact_id?: string;
}

export function useInboxEvents(): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    let cancelled = false;
    let retries = 0;
    let es: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    async function connect() {
      if (cancelled) return;
      try {
        const { data } = await api.post<{ ticket: string; expires_in: number }>("/events/ticket");
        if (cancelled) return;

        es = new EventSource(`${API_BASE_URL}/events/stream?ticket=${encodeURIComponent(data.ticket)}`);

        es.onopen = () => {
          retries = 0;
        };

        es.onmessage = (ev: MessageEvent<string>) => {
          let parsed: InboxRealtimeEvent;
          try {
            parsed = JSON.parse(ev.data);
          } catch {
            return; // malformed event — polling safety net covers it
          }
          queryClient.invalidateQueries({ queryKey: ["contacts"] });
          if (parsed.contact_id) {
            queryClient.invalidateQueries({ queryKey: ["messages", parsed.contact_id] });
          }
        };

        es.onerror = () => {
          // Close explicitly: the browser's default EventSource behavior is
          // to auto-reconnect the SAME URL, which would keep failing once
          // the ticket expires. We control reconnection ourselves so we can
          // mint a fresh ticket first.
          es?.close();
          es = null;
          if (cancelled) return;
          if (retries >= MAX_RETRIES) return; // give up for this session — polling remains
          retries += 1;
          retryTimer = setTimeout(connect, RETRY_BACKOFF_MS);
        };
      } catch {
        if (cancelled) return;
        if (retries >= MAX_RETRIES) return;
        retries += 1;
        retryTimer = setTimeout(connect, RETRY_BACKOFF_MS);
      }
    }

    connect();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      es?.close();
      es = null;
    };
  }, [queryClient]);
}

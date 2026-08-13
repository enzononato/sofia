# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multi-tenant SaaS for clinic management with an AI virtual assistant called **Sofia** (Google Gemini). Backend: FastAPI + SQLAlchemy 2.0 async + PostgreSQL. Frontend: Next.js 14 App Router + Tailwind CSS v3.

## Commands

### Backend
```bash
# Run dev server
venv\Scripts\uvicorn app.main:app --reload

# Run migrations
venv\Scripts\alembic upgrade head

# Create new migration
venv\Scripts\alembic revision --autogenerate -m "description"

# Rollback one migration
venv\Scripts\alembic downgrade -1

# Check imports / syntax
venv\Scripts\python -c "import app.main; print('OK')"

# Run the unit test suite (pure/in-memory — no DB, no Gemini)
venv\Scripts\python -m pytest tests/ -q
venv\Scripts\python -m pytest tests/test_crm.py -q   # single file

# Run the integration suite (real Postgres via docker compose, no Gemini —
# AI calls and outbound WhatsApp sends are mocked). Excluded from the default
# `pytest tests/` run via pytest.ini's --ignore, so it never surprises you.
docker compose up -d
venv\Scripts\python -m pytest tests/integration -q

# Manual E2E harness against the REAL Gemini API (costs money — never run in
# CI or automatically; see scripts/e2e_sofia.py's own docstring/CLI help)
venv\Scripts\python scripts\e2e_sofia.py --list
venv\Scripts\python scripts\e2e_sofia.py --scenario <name>

# Enable multimodal for a tenant
venv\Scripts\python -m scripts.enable_multimodal <slug>
```

### Frontend
```bash
cd frontend
npm run dev        # dev server (port 3000)
npm run build      # production build
npx tsc --noEmit   # type-check only (run before committing)
```

### Infrastructure (local)
```bash
docker compose up -d    # start postgres + pgadmin
docker compose down     # stop
```

pgAdmin at `localhost:5050` (no login required). Backend at `localhost:8000`, frontend at `localhost:3000`.

## Architecture

### Multi-tenancy
Every request must carry `X-Tenant-ID` header (UUID or slug). `TenantMiddleware` (`app/middleware/tenant.py`) resolves it from the DB and stores it in `request.state.tenant_id`. Public paths that bypass this are listed in `_PUBLIC_PATHS` — add new public endpoints there when needed.

`CurrentTenantId` and `CurrentUser` in `app/api/deps.py` are the typed FastAPI dependencies for route handlers. Cross-tenant token reuse is structurally blocked in `get_current_user`.

### Database schema
SQLAlchemy models in `app/models/`. All business models extend `TenantScopedMixin` (from `app/models/base.py`), which adds `tenant_id` — **every query must filter by `tenant_id`**. Never trust `tenant_id` from request bodies; always use `CurrentTenantId`.

If `DATABASE_SCHEMA` env var is set (e.g., `sofia`), the engine sets `search_path` via `connect_args` and Alembic uses `version_table_schema` — no code changes needed per table.

Migrations are linear (Alembic). Current head: `b7c8d9e0f1a2`. When adding a new model, register it in `app/models/__init__.py` so Alembic auto-detects it.

### Key models
- `Tenant` — clinic, has `settings` (JSONB) and `ai_config` (JSONB)
- `User` — roles: `owner / admin / receptionist / professional / viewer`
- `Contact` — WhatsApp contact, has `crm_stage` (CrmStage enum), `last_inbound_at`, `last_followup_at`, `human_takeover_until` (auto-pause window, see below), `handoff_alerted_at` (dedup for the "paused and forgotten" alert), `anonymized_at`/`anonymized_by_user_id` (LGPD, see Privacy section)
- `Appointment` — has `status`, `google_event_id`, `reminders` (JSONB)
- `Invitation` — email invite with `token_hash` + `expires_at`
- `GoogleCalendarCredential` — encrypted refresh token per professional

### AI (Sofia)
Entry point: `app/services/ai.py` → `generate_reply()`. Context building: `app/services/ai_stages.py` → `build_context_block()` (injects current datetime in clinic TZ, CRM stage, upcoming appointments). Tools: `app/services/ai_tools.py` (declared as `FunctionDeclaration`; executors in the same file; `execute_tool()` dispatches). Includes `confirm_appointment`, which the AI calls when the patient confirms presence (e.g. replying to a reminder) — moves `SCHEDULED → CONFIRMED`, never changes CRM stage.

**No human handoff — Sofia resolves every turn herself.** There is deliberately no conversational escalation: objections, price pushback, an insistent/upset patient, a complaint, or "quero falar com alguém" are all handled by Sofia's own conversation skills (Sales specialist / legacy prompt) — she never says she'll transfer to a human, and there is no `request_human_handoff`/`escalate_to_human` tool, no Handoff agent, and no `handoff` route in the Router. This is a product decision (medical-emergency valve was explicitly declined too — Sofia treats it as normal conversation, keeping the existing "no medical diagnosis / suggest in-person evaluation for a suspicious lesion" rules). `contact.ai_paused` is now set ONLY by the AI-usage caps or manually by staff in the Inbox — not by Sofia. If you reintroduce any handoff, restore the Router route + a specialist tool + the `_request_human_handoff` executor together.

**Staff copilot — "Sugerir resposta" (read-only).** `POST /contacts/{id}/suggest-reply` (in `contacts.py`, reached from the Inbox chat and the sidebar "Pedir ajuda à Sofia") asks Sofia to DRAFT a reply for a human to review and send. It calls `ai.py::generate_staff_suggestion`, which reuses Sofia's persona/context/tool-loop but with a **read-only tool subset** (`_SUGGESTION_READONLY_TOOLS` — list_services/get_clinic_info/list_professionals/check_availability/get_upcoming_appointments only; the allowlist gate in `run_specialist_loop` rejects any write tool even if hallucinated). The route **never commits** (rolls back) — a draft sends nothing, persists nothing, books nothing, and never touches `ai_paused`/the answered watermark. The returned text (with `[[BREAK]]` flattened) goes into the message input for the human to edit and send via the normal `POST /contacts/{id}/messages`. Roles: same `_WRITE_ROLES` + professional-scoping as the other contact endpoints.

**Fresh state at generate time.** Between a message arriving and Sofia replying there's a debounce/typing-hold window (seconds). `webhooks.py::_generate_and_send` re-opens a DB session and re-reads BOTH the `contact` AND the `tenant` fresh at that moment (not the snapshots captured when the webhook first arrived), so clinic settings/prices/policies and `ai_config` reflect the instant of generation. Appointments/availability/CRM stage are already queried at generate time (`ai_stages.analyze`, tools). Re-attaching the tenant to that session also makes the usage-cap pause write persist. Don't reintroduce a stale-tenant snapshot into the reply path.

**Prompt text has ONE home: `app/services/prompts.py`.** `SOFIA_CORE_PROMPT` (persona lock, human-tone rules, invariants, WhatsApp style) + `SALES_PLAYBOOK` + `BOOKING_PLAYBOOK`. The legacy path composes `DEFAULT_SYSTEM_PROMPT = CORE + SALES + BOOKING` (it declares every tool); the multi-agent path uses `SHARED_BASE_PROMPT = CORE` and each specialist appends its own playbook via `OVERLAY`. Before this, the two prompts were parapharased copies (124/149 lines identical) that had already diverged, so every fix had to be made twice and one was always forgotten. Three writing rules are enforced by `tests/test_prompt_invariants.py`: **no em-dashes in the prompt body** (the prompt bans them for Sofia, and the system prompt is the strongest style example the model gets), **no ready-to-send quoted sentence for a specific trigger** (with no variation pressure the model emits it verbatim, so two patients get byte-identical replies), and **no rule may name a tool the agent of that turn doesn't hold** (ground facts in the context block instead).

**Two generation paths, one prompt.** `generate_reply()` dispatches on `multi_agent_enabled_for(tenant)`: the per-clinic `ai_config["multi_agent_enabled"]` (exposed as a toggle in Settings → IA) wins when it's an explicit bool, else the global `AI_MULTI_AGENT_ENABLED` (default `False`). The multi-agent path costs 2-3 Gemini calls per turn (Router + 1-2 specialists) versus 1, so it ships off and is opted into per clinic. **Tool partition**: WRITE tools are exclusive (Booking owns create/reschedule/cancel + `update_contact_info`; Sales owns `set_crm_stage`), but READ tools are deliberately shared — Sales is the Router's fallback route, so it also holds `check_availability`/`get_upcoming_appointments`/`confirm_appointment` (a patient answering "sim, confirmo" to a reminder can land there, and that confirmation must not be lost), and Booking holds `get_clinic_info` (a patient mid-booking asking the address must not get a stall or an invention). `tests/test_agents_tool_partition.py` pins both the exclusivity and the coverage. Both paths run the SAME tool-calling loop, `app/services/agents/base.py::run_specialist_loop`, parameterized by `system_prompt`/`tools`/`allowed_tool_names`/`max_iterations` (the legacy path passes 8, specialists take the default 4). The staff "Sugerir resposta" copilot (above) is the third caller. Before this, `_legacy_generate_reply` carried a hand-rolled copy of the same loop, down to two byte-identical patient-facing fallback strings — the same "two paraphrased copies, every fix made twice, one always forgotten" failure this file already documents for the prompts above.

**Log event slugs**: the shared loop emits the `agent_*` event family (`agent_reply_ready`, `agent_tool_executed`, `agent_empty_parts`, `agent_tool_loop_exhausted`, `agent_tool_not_allowed`, `agent_forced_final_reply`, plus a debug-level `agent_iteration`), which replaced the old `gemini_*`/`ai_tool_executed` slugs when the legacy hand-rolled loop was removed. Anyone reading logs or writing an alert on these events should match on the new names. `agent_reply_ready` is not strictly one-per-turn: in the multi-agent path's COMPOSITE mode (`orchestrator.py` runs two specialists sequentially for one patient reply), each specialist's `run_specialist_loop` call logs its own `agent_reply_ready`, so an operator sees two lines for that single turn. The friendly-label registry for the dev console formatter is `_EVENT_STYLE` in `app/core/logging.py`.

**Sofia is a person to the patient — never an AI.** The prompt forbids revealing she's an AI/bot/virtual assistant; if asked, she deflects without confirming or denying. `generate_reply` accepts a list of media so a burst of several audios/images is all forwarded to Gemini (not just the last). Clinic settings expose structured `max_installments` and evaluation policy (`evaluation_fee_mode`/`evaluation_fee`/`evaluation_fee_deductible`) via `get_clinic_info` so Sofia never invents payment or consultation prices. `check_availability`/booking reject any time in the past (with a small `MIN_BOOKING_LEAD_MINUTES` lead, default 30) — a patient asking "today" late in the day never sees or books an already-elapsed slot.

**Gemini call resilience**: transient failures in the `generate_content` call get 1-2 quick retries (`app/services/ai.py::_generate_content_with_retry`, distinct from the existing empty-candidate retry). If every attempt fails, `generate_reply` raises `AIGenerationError` instead of returning a robotic "problema técnico" message — the caller (`webhooks.py::_generate_and_send`) rolls back and does NOT advance the "answered" watermark, so the patient's question is naturally retried on their next message or by the post-restart recovery sweep (below), rather than the AI ever sounding like a system error.

**AI usage caps** (`AI_USAGE_LIMITS_ENABLED`, default `True`): a contact capped at `AI_USAGE_CAP_PER_CONTACT_DAILY` (default 40) auto-replies/day gets paused (`ai_paused=True`) with an email alert (`app/services/alerts.py::send_handoff_alert_email`); a tenant capped at `AI_USAGE_CAP_PER_TENANT_DAILY` (default 400) has its auto-replies stopped tenant-wide with a separate alert (`send_tenant_usage_cap_alert_email`). Both counts are plain SQL queries over `Message` (no new infra), evaluated in `app/api/v1/routes/webhooks.py`.

**Security invariant**: `tenant_id` and `contact_id` are **never** taken from AI tool arguments — always injected from Python context. The AI cannot forge these values.

**Hallucinated IDs fail loudly.** A `service_id`/`new_service_id` the model invented (observed in real E2E transcripts: `list_services` returned one UUID, the next call used a different, non-existent one) is REJECTED by `create_appointment`/`check_availability`/`reschedule_appointment` in **both** scheduling modes. The capacity path used to swallow it (`if svc:` simply didn't match), creating the appointment with `service_id=NULL` and the default 60-min duration while Sofia told the patient the procedure by name — a booked slot with no procedure. Both prompts also carry an explicit "copy IDs character by character, never invent one" rule next to the existing date rule.

**Media never lives in `messages.content`.** Both the inbound webhook and `POST /contacts/{id}/messages/media` store the data URI in `media_url` with `media_type`/`media_mime_type`/`media_size_bytes` set, leaving `content` for the caption. The staff-media route used to put the whole base64 blob in `content` with `media_type` NULL, so `ai.py::_history_text_for` fell through to `return msg.content` and fed the entire blob to Gemini **as text on every later turn** for that contact — cost blowup, then context-limit failures that silently stopped replies. Migration `c8d9e0f1a2b3` repairs pre-existing rows; `_history_text_for` also guards defensively against any `content` starting with `data:`.

### WhatsApp humanization pipeline
Three layered behaviors, all in `app/services/`, all single-worker (same constraint as the scheduler):

1. **Message batching** (`message_batcher.py`): asyncio debounce registry keyed by `contact_id`. `schedule()` cancels any pending timer and starts a new one (15–20 s random window, `BATCH_WINDOW_MIN/MAX_SECONDS`). When the timer fires, `_generate_and_send()` re-reads **all unanswered inbound messages** from the DB and replies once to the whole burst. Media messages call `flush()` instead, which runs immediately.

   **Presence-aware hold**: the webhook subscribes to the UAZAPI `presence` event (events list in `whatsapp_instance.py`). `_handle_presence_update()` in `webhooks.py` feeds a typing registry keyed by `{tenant_id}:{phone}` (`mark_typing`/`clear_typing`). After the debounce window elapses, `_debounced_run` keeps waiting while the contact is still `composing`/`recording`/`paused` (capped by `TYPING_MAX_HOLD_SECONDS`), so Sofia answers the whole burst instead of each fragment. Degrades to plain debounce if the provider never sends presence events. Toggle via `PRESENCE_TYPING_ENABLED`. **Re-provisioning the webhook events requires the tenant to reconnect WhatsApp** (the events list is re-applied on connect via `set_webhook`).

2. **Partitioned replies** (`humanizer.py` → `split_reply()`): AI is instructed (via `DEFAULT_SYSTEM_PROMPT`) to separate parts with `[[BREAK]]`. The function splits on this marker first; if absent and the text exceeds `RESPONSE_SPLIT_MAX_CHARS` (320 chars), it falls back to paragraph/sentence splitting. Always returns `list[str]`.

3. **Human behavior simulation** (`whatsapp.py` + `webhooks.py`): before replying, `mark_messages_as_read()` sends blue ticks (best-effort, swallows errors). Then for each part: `send_presence("composing")` → `asyncio.sleep(typing_delay_seconds(part))` → `send_text_message()` → `_save_outbound()`. Typing delay is proportional to part length / `TYPING_CHARS_PER_SECOND`, clamped to `[TYPING_MIN_SECONDS, TYPING_MAX_SECONDS]`, with ±`TYPING_JITTER` (15%) random variation.

All behaviors can be disabled independently via env flags (`MESSAGE_BATCHING_ENABLED`, `PRESENCE_TYPING_ENABLED`, `RESPONSE_SPLIT_ENABLED`, `TYPING_SIMULATION_ENABLED`, `READ_RECEIPT_ENABLED`). Best-effort functions (`send_presence`, `mark_messages_as_read`) must never raise — they log a warning and return.

Scheduling modes in `ai_config.scheduling_mode`: `capacity` (N simultaneous per clinic) or `per_professional` (per-professional availability).

**Human takeover auto-pause**: a WhatsApp message with `fromMe=true, wasSentByApi=false` (staff typed directly in the phone app/WhatsApp Web, not through the SaaS) is recorded as a normal OUTBOUND `Message` (so Sofia's context stays consistent with what staff already said) and sets `Contact.human_takeover_until = now + HUMAN_TAKEOVER_PAUSE_MINUTES` (default 60, renewed — not stacked — on every such message). Every reply-decision point (`webhooks.py`'s dispatch, `_generate_and_send`, and the post-restart recovery sweep) checks this window alongside `ai_paused` — self-expiring, no manual un-pause needed, unlike `ai_paused` (which stays until staff clear it in the Inbox). The rule itself has ONE home: `app/services/takeover.py`, exposing `in_human_takeover(contact, now)` for per-contact decisions and `not_in_human_takeover_clause(now)` for the recovery sweep's aggregate query. It used to be expressed three times — twice in `webhooks.py` (a function and an inline SQL predicate) and once in `followups.py` — keeping both forms adjacent in one module makes a semantic change one visible edit instead of three.

**Pending-reply recovery sweep**: finds contacts whose last message is INBOUND, unanswered, not paused, aged between ~2 min and ~6 h, and re-schedules a reply via the normal batcher. Runs at FastAPI startup **and** as a scheduler job every `RECOVERY_SWEEP_JOB_MINUTES` (default 5). Boot-only was not enough: a message delivered >5 min late is stored with `is_historical=True` and never answered (happens whenever UAZAPI reconnects and flushes its offline backlog), and a turn where every Gemini attempt failed deliberately leaves the burst unanswered *expecting this sweep to retry it* — with the process up for days, boot-only meant "never".

**Proactive sends are gated** (`followups.py::can_send_proactive`, pure/testable): reminders and re-engagement never fire for a contact with `ai_paused`, never talk over an active `human_takeover_until` window, and never go out outside the clinic's hours. The scheduler uses `interval` jobs anchored to process boot, so without the window a 21h deploy had re-engagement firing at 03h local — a "human secretary" texting at 3am is the loudest possible tell. The window comes from `settings.schedule` (open/close/working_days), overridable via `settings.followups.send_window = {"start","end"}`. Reminders skipped this way are **not** marked as sent, so the next run picks them up once the clinic opens. Reminder wording also drops the name when `Contact.full_name` is really the phone number (the WhatsApp push-name fallback — this produced literal "Olá, 5511987654321!") and filters out greetings that contradict the clock.

### CRM auto-classification
Kanban stages (`CrmStage`): `new_lead` → `cold_lead` / `hot_lead` → `scheduled` → `attended` → `post_care`, plus `lost`. A contact stays in `new_lead` until Sofia qualifies it as `cold_lead` (low intent) or `hot_lead` (clear buying intent) — inbound messages no longer auto-advance the stage. Two-layer approach:
1. **Deterministic** (`app/services/crm.py`): `mark_inbound()` only records `last_inbound_at` (does NOT change stage), `mark_scheduled()` on appointment create, `mark_attended()` on appointment completion. Uses set logic (`_SCHEDULED_OR_PAST`, `_ATTENDED_OR_PAST`) so `lost` contacts can be revived.
2. **AI tool** `set_crm_stage`: Sofia can set `cold_lead`, `hot_lead`, `post_care`, `lost`. Never sets `scheduled`/`attended` (those are factual). Manual drags from the Kanban set `crm_stage_source="manual"`. The executor also **refuses to regress a factual stage** (`_FACTUAL_STAGES`): the prompt asks Sofia to classify on every turn, so a patient who already had a slot booked and then said "vou pensar" used to be dragged from `scheduled` back to `cold_lead`, losing the booking from the funnel view. `lost` is still allowed through (an explicit give-up is real information).

### Background scheduler
`app/services/scheduler.py` — APScheduler `AsyncIOScheduler` started in FastAPI lifespan. Jobs: appointment reminders (varied wording across the 6 templates in `followups.py`, not a fixed string), re-engagement (now references the contact's actual recent conversation, not a generic nudge), Google Calendar reconciliation, and `run_paused_alert` (every `HANDOFF_ALERT_JOB_MINUTES`, default 10 — emails the clinic once per pause "episode" when a paused contact's inbound message has gone unanswered too long, deduped via `Contact.handoff_alerted_at`; the pause now comes from a usage cap or a manual Inbox pause, since Sofia no longer hands off). Per-clinic config in `tenant.settings.followups` (read by `app/services/followups.py`). **Run only 1 uvicorn worker** in production to avoid duplicate sends.

### Security
- `TenantRead` schema (`app/schemas/tenant.py`) strips all secrets via `field_validator` — `gemini_api_key`, `webhook_secret`, `api_key`, `api_url` are never serialized to clients. The same key set (`_SENSITIVE_WHATSAPP_KEYS`) is also enforced on the WRITE path: `PATCH /tenants/me` silently drops any of those keys (plus `status`/`instance`) from an incoming `settings.whatsapp` payload before merging, so a clinic admin can never overwrite the server-managed WhatsApp connection state via a normal settings save. `plan`/`is_active` are not in `TenantUpdate` at all — not self-service.
- Google OAuth refresh tokens encrypted at rest via Fernet (`app/core/crypto.py`). Key from `ENCRYPTION_KEY` env or derived from `SECRET_KEY`.
- `SecurityHeadersMiddleware` (`app/middleware/security_headers.py`) adds HSTS, X-Frame-Options, etc.
- WhatsApp webhook secret validation is **fail-closed**: a tenant with no `webhook_secret` stored rejects every request (previously fail-open). Comparison uses `hmac.compare_digest`. `messages.whatsapp_message_id` has a real partial UNIQUE index on `(tenant_id, whatsapp_message_id)` (not just an app-level SELECT-before-INSERT check), so two concurrent webhook deliveries for the same message can't both land.
- `professional`-role users are scoped to contacts they have an `Appointment` with — enforced consistently across every contact detail/message/update endpoint in `app/api/v1/routes/contacts.py`, not just the list endpoint.
- Refresh-token replay detection revokes the whole token family and **commits that revocation before raising** — `get_db()` rolls back the ambient session on any exception, so a flush-only revocation would otherwise be silently discarded (this was a real bug, fixed; see `app/services/tokens.py::rotate_refresh_token`).

### Privacy / LGPD (manual only — no automated retention job)
`app/services/privacy.py` + `app/api/v1/routes/privacy.py`: `GET /contacts/{id}/export` (full structured JSON of a contact's data — owner/admin/receptionist) and `POST /contacts/{id}/anonymize` (irreversible PII scrub — owner/admin only). Anonymizing clears `Contact.phone` too, so a future WhatsApp message from that number starts a fresh contact instead of reattaching to the anonymized record. `Message` rows are kept with `content`/media scrubbed (not deleted) so volume reporting doesn't develop gaps. No scheduled deletion/retention automation exists — this is a deliberate product decision, revisit only with an explicit go-ahead.

### Frontend
Axios instance in `frontend/src/lib/axios.ts` has `baseURL = NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'`. **Always use the `api` instance for requests — never raw `axios`** to avoid double `/api/v1` prefix. Hooks call paths without the prefix (e.g., `api.get('/contacts')`).

State management: Zustand (`useAuthStore`) for auth. Server state: TanStack React Query v5. All hooks in `frontend/src/hooks/`.

Tailwind is **v3** — shadcn/ui may generate v4 classes, always convert manually when adding components.

### Role-based access (frontend)
`userRole` is read from `useAuthStore`. Sidebar items marked `adminOnly` are hidden for `professional` role. Backend enforces scope: professionals see only their own appointments and contacts.

### Testing
Two backend suites, deliberately separated (see `pytest.ini`'s `--ignore=tests/integration`, so a bare `pytest tests/` never needs a DB):
- `tests/` — pure/in-memory, no DB, no network. Fast, run constantly.
- `tests/integration/` — real Postgres (via `docker compose up -d`), a real FastAPI app over `httpx.ASGITransport`, two seeded tenants. Gemini/UAZAPI calls are mocked (`AsyncMock`, patched where the name is *imported*, not where it's defined). Covers tenant isolation, auth (login/refresh-rotation/replay/rate-limit), the privacy endpoints, and the webhook pipeline end-to-end (fail-closed secret, idempotency, group/historical-message skipping, human-takeover pause, usage caps, `confirm_appointment`). Background tasks: `ASGITransport` awaits FastAPI `BackgroundTasks` before the response returns, but `message_batcher`'s inner `asyncio.create_task` is fire-and-forget regardless — tests poll (`_wait_until`-style helpers) rather than assume synchronous completion.
- `scripts/e2e_sofia.py` — standalone, **manual-only**, hits the real Gemini API against a throwaway tenant (cleaned up after every run). Never run automatically/in CI — it costs money. `--list` to see scenarios, `--scenario <name>` for one, `--all` asks for interactive confirmation first.

## Critical constraints

- `bcrypt==3.2.2` — used directly (via `bcrypt.hashpw`/`bcrypt.checkpw` in `app/core/security.py`, no longer via passlib, which was dropped in favor of PyJWT/direct-bcrypt for both being actively maintained). The pin is now a deliberate, conservative choice validated against the `$2b$...` hashes already in the DB — bump intentionally and re-test rather than let it drift.
- `httpx==0.28.1` — required by google-genai 1.10. Do not upgrade httpx.
- Alembic migrations are linear — never create a branch. Always `alembic upgrade head` before creating a new revision.
- WhatsApp integration uses **UAZAPI** (`UAZAPI_URL` + `UAZAPI_ADMIN_TOKEN`). Each clinic gets its own UAZAPI instance created via the admin token; the per-instance `token` (auth for that clinic's sends) is stored in `tenant.settings["whatsapp"]["token"]` and, like `webhook_secret`, is never returned by the API. UAZAPI can't send custom webhook headers, so the per-tenant secret rides in the webhook URL's `?token=` query param and is validated on receipt. Webhook events subscribed: `messages`, `connection`, `presence`.
- `SCHEDULER_ENABLED=false` to prevent real WhatsApp sends during development/testing.
- **1 uvicorn worker only** in production — both the APScheduler and the message-batcher debounce registry are in-process state. Multi-worker would require Redis for both.
- No Redis / horizontal scaling in this phase — a deliberate product decision, not a gap someone forgot. Don't propose Redis-backed rate limiting, distributed batching, etc. without an explicit product go-ahead.
- Media stays stored as base64 data URIs in `messages.media_url` (Postgres `TEXT`) — no object storage (S3/R2/etc.) migration planned for this phase, also a deliberate decision. `_fetch_history` and the contacts-listing preview both `defer`/omit `media_url` so it's only ever loaded when the open conversation actually needs it — don't undo that by casually re-selecting the full ORM object in a new code path.

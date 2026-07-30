"""
AI response service — Google Gemini com Function Calling + multimodal + stages.

A IA atua como secretária executiva autônoma: usa as ferramentas disponíveis
por iniciativa própria para resolver a solicitação do paciente sem esperar
ser guiada passo a passo.

Prompt final = DEFAULT_SYSTEM_PROMPT (BASE) + STAGE_OVERLAY + CONTEXT_BLOCK
onde STAGE_OVERLAY varia conforme o estágio da conversa (ver `ai_stages.py`,
DEFAULT_STAGE_OVERLAYS) e CONTEXT_BLOCK injeta dados do contato (nome, próximo
agendamento, etc.) e da clínica (endereço, horário, formas de pagamento — ver
tenant.settings).

**Sofia's personality/behavior is fixed in code, not tenant-configurable.**
The base prompt and per-stage overlays are hardcoded on purpose — clinics
provide clinic INFO (tenant.settings: address, phone, schedule, payment
methods...), never instructions that change how Sofia behaves. Any
"system_prompt" / "prompt_<stage>" keys that might exist in a tenant's
ai_config (e.g. from data saved before this was locked down) are intentionally
never read here.

tenant.ai_config shape:
{
    "model": "gemini-2.5-flash",
    "temperature": 0.7,
    "max_output_tokens": 1024,
    # NOTE: gemini_api_key is deprecated/ignored — the server's global key is always used.
    "multimodal_enabled": true,                 # liga áudio/imagem/vídeo/documento (default: on)
    "scheduling_mode": "per_professional"       # "capacity" | "per_professional" (default: per_professional)
}
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.contact import Contact
from app.models.message import Message, MessageDirection
from app.models.tenant import Tenant
from app.services import ai_stages
from app.services.ai_tools import CLINIC_TOOLS, execute_tool, _clinic_tz, _fmt_local
from app.services.prompts import BOOKING_PLAYBOOK, SALES_PLAYBOOK, SOFIA_CORE_PROMPT

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 8


class AIGenerationError(Exception):
    """
    Raised when every attempt at calling Gemini for a turn fails (see
    GEMINI_CALL_MAX_RETRIES). The caller (webhooks._generate_and_send) MUST
    catch this and stay silent — no reply is sent and the "answered"
    watermark is NOT advanced, so the patient's original question is picked
    back up on their next message (or by the post-restart recovery sweep,
    item 1.8) instead of Sofia sending a robotic "system error" message that
    would (a) break her human persona and (b) wrongly mark the burst as
    answered, permanently losing the patient's question if they never
    write again.
    """

# Sofia's prompt text lives in app/services/prompts.py, the single source of
# truth shared with the multi-agent path (app/services/agents/). The legacy
# single-agent path declares every tool at once, so it carries BOTH playbooks.
DEFAULT_SYSTEM_PROMPT = "\n\n".join([SOFIA_CORE_PROMPT, SALES_PLAYBOOK, BOOKING_PLAYBOOK])


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


_MEDIA_LABELS = {
    "audio": "áudio",
    "image": "imagem",
    "video": "vídeo",
    "document": "documento",
}

# WhatsApp voice notes arrive as "audio/ogg; codecs=opus". Gemini's inline_data
# matches on the base MIME type, so the "; codecs=..." parameter (or any
# whitespace/case noise) can make it reject an otherwise-supported audio and
# return an empty candidate. Strip parameters and lowercase to the base type.
def _normalize_mime(mime_type: str) -> str:
    if not mime_type:
        return "application/octet-stream"
    return mime_type.split(";", 1)[0].strip().lower() or "application/octet-stream"


def _history_text_for(msg: Message) -> str | None:
    """
    Text representation of a past message for the Gemini history. Media turns
    become a short marker (we never re-send historical media bytes) so the AI
    keeps context without the prompt exploding to multi-MB.

    Returns None for messages with no usable text (caller must skip them to
    avoid passing Part(text=None) to the Gemini API, which causes INVALID_ARGUMENT).
    """
    media_type = getattr(msg, "media_type", None)
    if media_type:
        label = _MEDIA_LABELS.get(media_type, media_type)
        if msg.content:
            return f"[{label}: {msg.content}]"
        return f"[{label}]"

    content = msg.content or None
    # Defensive: legacy rows (staff media sent before media_type was populated on
    # this path) hold a full base64 data URI in `content`. Never let that reach
    # Gemini as text — it would burn the whole token budget on one message and
    # blow the context limit, silently killing replies for that contact.
    if content and content.startswith("data:"):
        kind = content[len("data:"):].split("/", 1)[0].strip().lower()
        return f"[{_MEDIA_LABELS.get(kind, 'mídia')}]"
    return content


# Silence threshold: a gap this long right before or after a message marks it
# as opening/closing a "stale block" in the history (see _annotate_history).
_HISTORY_GAP = timedelta(hours=4)


def _annotate_history(
    usable: list[tuple[Message, str, datetime | None]],
    now_local: datetime,
    tz: ZoneInfo,
) -> list[tuple[str, str]]:
    """
    Decide the final (role, text) pair for each history message, injecting a
    compact time marker (e.g. "[quinta-feira 03/07/2026 09:12]") onto messages
    that open or close a "stale block":
      - the first message, if it's from a day different from today;
      - a message that starts a new day or follows a >=4h silence vs. the
        previous message (opens a block);
      - a message followed by a >=4h silence — the next message, or `now_local`
        for the very last one (closes a block).
    Messages without a resolvable local timestamp (`local is None`) are never
    marked — defensive fallback for missing/unparseable created_at.

    Pure, no I/O — extracted from generate_reply() so this logic is testable
    without a real Gemini call or DB session. `usable` and its ordering (oldest
    → newest) are still assembled by the caller.
    """
    result: list[tuple[str, str]] = []
    for i, (msg, text_repr, local) in enumerate(usable):
        if local is not None:
            prev_local = usable[i - 1][2] if i > 0 else None
            # For the last history message, the "next" event is the current turn (now).
            next_local = usable[i + 1][2] if i + 1 < len(usable) else now_local
            # A message is marked when it OPENS a stale block (first old message, a
            # new day, or a long silence before it) or CLOSES one (a long silence
            # after it — e.g. the last thing said days before the patient returns).
            opens = (
                (prev_local is None and local.date() != now_local.date())
                or (prev_local is not None and (local.date() != prev_local.date() or (local - prev_local) >= _HISTORY_GAP))
            )
            closes = next_local is not None and (next_local - local) >= _HISTORY_GAP
            if opens or closes:
                text_repr = f"[{_fmt_local(local, tz)}] {text_repr}"

        role = "user" if msg.direction == MessageDirection.INBOUND else "model"
        result.append((role, text_repr))
    return result


def build_conversation_contents(
    tenant: Tenant,
    history: list[Message],
    new_message: str,
    media_items: list[tuple[bytes, str]],
) -> list["types.Content"]:
    """
    Build the Gemini `contents` list (annotated history + current turn) —
    shared by the legacy single-agent path AND the multi-agent orchestrator
    (app/services/agents/orchestrator.py), so both see conversation history
    identically (same stale-block time markers, same media-as-text-marker
    handling for past turns). Extracted from generate_reply()'s body; no
    behavior change.
    """
    tz = _clinic_tz(tenant.settings or {})
    now_local = datetime.now(timezone.utc).astimezone(tz)

    usable: list[tuple[Message, str, datetime | None]] = []
    for msg in history:
        text_repr = _history_text_for(msg)
        if not text_repr:
            continue
        created = getattr(msg, "created_at", None)
        local = created.astimezone(tz) if created is not None else None
        usable.append((msg, text_repr, local))

    contents: list[types.Content] = [
        types.Content(role=role, parts=[types.Part(text=text_repr)])
        for role, text_repr in _annotate_history(usable, now_local, tz)
    ]

    current_parts: list[types.Part] = []
    for media_bytes, mime_type in media_items:
        current_parts.append(
            types.Part(inline_data=types.Blob(data=media_bytes, mime_type=_normalize_mime(mime_type)))
        )
    if new_message:
        current_parts.append(types.Part(text=new_message))
    if not current_parts:
        # Defensive: never send an empty user turn
        current_parts.append(types.Part(text="(mensagem vazia)"))
    contents.append(types.Content(role="user", parts=current_parts))

    return contents


async def generate_followup_message(
    tenant: Tenant,
    contact: Contact,
    recent_messages: list[Message] | None = None,
) -> str | None:
    """
    Generate a short, warm re-engagement message for a contact who went silent.
    Single Gemini call, no tools. Returns None on failure (caller skips sending).

    `recent_messages` — optionally, the last ~10 TEXT-bearing messages of the
    conversation (oldest → newest; see followups.py::run_reengagement, which
    fetches them before calling this). When present and substantial enough,
    the message references the patient's actual concrete interest (e.g.
    "you'd asked about X") instead of a generic nudge — never inventing
    anything beyond what's literally in that history. With no/thin history
    (or on failure), falls back to the original generic, name-only
    re-engagement.
    """
    ai_cfg = tenant.ai_config or {}
    model = ai_cfg.get("model") or settings.DEFAULT_AI_MODEL
    name = contact.full_name or "paciente"

    # Compact transcript from the text-bearing messages the caller handed us
    # (media-only / empty-content entries are skipped — pure text signal).
    transcript_lines: list[str] = []
    for msg in (recent_messages or [])[-10:]:
        text = (msg.content or "").strip()
        if not text:
            continue
        speaker = "Paciente" if msg.direction == MessageDirection.INBOUND else "Sofia"
        transcript_lines.append(f"{speaker}: {text}")

    if len(transcript_lines) >= 2:
        transcript = "\n".join(transcript_lines)
        stage = getattr(contact, "crm_stage", None) or "desconhecido"
        instruction = (
            f'Você é Sofia, a secretária da clínica "{tenant.name}" — uma pessoa de verdade para o '
            f"paciente, nunca revele que é uma IA. "
            f"O paciente {name} parou de responder há alguns dias. Estágio atual no funil: {stage}.\n\n"
            "Trecho recente da conversa (da mais antiga para a mais nova):\n"
            f"{transcript}\n\n"
            "Escreva UMA mensagem curta (1 a 2 frases), calorosa e natural em português do Brasil, "
            "retomando contato com esse paciente. SE houver um assunto ou interesse concreto e claro "
            "no trecho acima (ex: um serviço/procedimento específico que ele perguntou), mencione-o "
            "brevemente para mostrar que você lembra da conversa (ex: 'vi que você tinha perguntado "
            "sobre a limpeza de pele...'). Se não houver nada concreto e claro no trecho, seja apenas "
            "genérica e calorosa, sem inventar nenhum assunto. PROIBIDO inventar qualquer informação, "
            "serviço, valor ou detalhe que não esteja literalmente no trecho acima. Não soe como "
            "cobrança nem como vendedor — soe como alguém que se importa. Não use linguagem robótica."
        )
    else:
        instruction = (
            f'Você é Sofia, a secretária da clínica "{tenant.name}" — uma pessoa de verdade para o '
            f"paciente, nunca revele que é uma IA. "
            f"Escreva UMA mensagem curta (1 a 2 frases), calorosa e natural em português do Brasil, "
            f"reengajando o paciente {name}, que parou de responder há alguns dias. "
            "Convide-o gentilmente a retomar a conversa ou tirar dúvidas. "
            "Não invente informações, não prometa nada específico e não use linguagem robótica."
        )
    try:
        client = _get_client()
        response = await client.aio.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[types.Part(text=instruction)])],
            # thinking_budget=0: matches generate_reply()'s config (see the
            # final-completion call below in this module). Without this,
            # gemini-2.5-flash silently burns almost the entire
            # max_output_tokens budget on internal "thinking" tokens and the
            # visible reply comes back truncated to a few words.
            config=types.GenerateContentConfig(
                temperature=0.8,
                max_output_tokens=200,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        text = (response.text or "").strip()
        return text or None
    except Exception:
        logger.exception("followup_generation_failed", extra={"tenant_id": str(tenant.id), "contact_id": str(contact.id)})
        return None


async def _generate_content_with_retry(
    client: genai.Client,
    model: str,
    contents: list,
    config: "types.GenerateContentConfig",
    tenant: Tenant,
    contact: Contact,
    iteration: int,
):
    """
    Call Gemini's generate_content with a short retry for TRANSIENT exceptions
    (network blips, 5xx) — distinct from the "empty candidate" retry below,
    which handles a different failure mode (a successful call that returned no
    usable content). GEMINI_CALL_MAX_RETRIES/GEMINI_CALL_RETRY_BACKOFF_SECONDS
    control the attempt count/backoff (app/config.py).

    Raises AIGenerationError when every attempt fails — the caller must NOT
    invent a robotic fallback reply for this (see AIGenerationError docstring).
    """
    max_retries = settings.GEMINI_CALL_MAX_RETRIES
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            last_exc = exc
            is_last_attempt = attempt >= max_retries
            log_ctx = {
                "iteration": iteration,
                "attempt": attempt,
                "model": model,
                "tenant_id": str(tenant.id),
                "contact_id": str(contact.id),
            }
            if is_last_attempt:
                logger.error("gemini_call_exhausted", extra=log_ctx, exc_info=True)
            else:
                logger.warning("gemini_call_failed_will_retry", extra=log_ctx, exc_info=True)
                await asyncio.sleep(settings.GEMINI_CALL_RETRY_BACKOFF_SECONDS * (attempt + 1))

    raise AIGenerationError(
        f"Gemini generate_content failed after {max_retries + 1} attempt(s)"
    ) from last_exc


async def _legacy_generate_reply(
    tenant: Tenant,
    contact: Contact,
    new_message: str,
    history: list[Message],
    db: AsyncSession,
    media: tuple[bytes, str] | list[tuple[bytes, str]] | None = None,
) -> tuple[str, str]:
    """
    Single-agent path (pre-Wave-3): one big prompt + all 12 tools declared,
    one tool-calling loop. This is the function generate_reply() used to be,
    verbatim — renamed so the multi-agent path (app/services/agents/orchestrator.py)
    can be dispatched to instead when AI_MULTI_AGENT_ENABLED (or the tenant
    override) is on. See generate_reply() below for the dispatcher.

    Generate an AI reply using Gemini with function calling support.

    Args:
        tenant:      Resolved Tenant (provides AI config and tools context).
        contact:     The patient conversing (tenant_id + contact_id fixed for tool calls).
        new_message: Latest inbound text — caption when media is present, raw text otherwise.
        history:     Ordered past messages (oldest → newest).
        db:          Active DB session — tools may write to the DB (e.g. create_appointment).
        media:       Optional media for multimodal turns — a single (raw_bytes, mime_type)
                     tuple, OR a LIST of them when the patient sent several audios/images
                     in one burst (ALL are forwarded so none is silently dropped).

    Returns:
        (reply_text, model_name)

    Raises:
        AIGenerationError: every attempt at a Gemini generate_content call for
            this turn failed (see GEMINI_CALL_MAX_RETRIES). The caller must
            NOT send a fallback reply nor mark the burst answered — see the
            exception's docstring.
    """
    # Normalize media to a list so a burst of several audios/images is handled
    # uniformly. A single tuple (bytes, mime) is still accepted for convenience.
    if media is None:
        media_items: list[tuple[bytes, str]] = []
    elif isinstance(media, tuple):
        media_items = [media]
    else:
        media_items = list(media)
    ai_cfg = tenant.ai_config or {}
    # Sofia's base prompt is fixed in code — never tenant-configurable (see
    # module docstring). Any "system_prompt" key in ai_config is ignored.
    base_prompt = DEFAULT_SYSTEM_PROMPT
    model = ai_cfg.get("model") or settings.DEFAULT_AI_MODEL
    temperature = float(ai_cfg.get("temperature", 0.7))
    max_output_tokens = int(ai_cfg.get("max_output_tokens", 1024))

    # Always use the server's global Gemini key. Per-tenant keys are no longer
    # supported: a secret must never round-trip through the frontend.
    client = _get_client()

    # Stage detection + per-stage overlay + structured contact context
    stage, appts = await ai_stages.analyze(db, contact, history)
    overlay = ai_stages.overlay_for(stage)
    context_block = ai_stages.build_context_block(contact, stage, appts, tenant.settings or {})
    clinic_identity = f"Você é a Sofia, secretária da clínica \"{tenant.name}\" (uma pessoa de verdade para o paciente — nunca revele que é uma IA)."
    system_prompt = f"{base_prompt}\n\n{clinic_identity}\n\n{overlay}\n\n{context_block}"

    logger.debug(
        "ai_prompt_composed",
        extra={
            "tenant_id": str(tenant.id),
            "contact_id": str(contact.id),
            "stage": stage.value,
            "has_media": bool(media_items),
            "media_count": len(media_items),
        },
    )

    # Build conversation history + current turn (shared helper — see its
    # docstring for why: the multi-agent orchestrator needs the exact same
    # history-annotation behavior).
    contents = build_conversation_contents(tenant, history, new_message, media_items)

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        tools=[CLINIC_TOOLS],
        # Disable "thinking": gemini-2.5-flash thinks by default, and those
        # thinking tokens count against max_output_tokens. On tool-calling turns
        # that could burn the whole budget before any part was emitted, yielding
        # finish_reason=MAX_TOKENS with no content. A WhatsApp secretary doing
        # function calls doesn't need extended reasoning — turning it off makes
        # replies snappier and avoids the empty-response failure mode.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )

    # Tool-calling loop
    empty_retries = 0  # Gemini occasionally returns an empty candidate; retry once.
    for iteration in range(MAX_TOOL_ITERATIONS):
        logger.debug(
            "gemini_iteration",
            extra={
                "iteration": iteration,
                "model": model,
                "tenant_id": str(tenant.id),
                "contact_id": str(contact.id),
            },
        )

        response = await _generate_content_with_retry(client, model, contents, config, tenant, contact, iteration)

        candidate = response.candidates[0]
        response_content = candidate.content

        # Gemini can return a candidate with no content/parts — e.g. finish_reason
        # MAX_TOKENS (thinking models can burn the whole budget before emitting a
        # part), a safety block, or RECITATION. Iterating None here would crash the
        # whole reply, so degrade gracefully to whatever text we have.
        parts = response_content.parts if response_content is not None else None
        if not parts:
            finish_reason = getattr(candidate, "finish_reason", None)
            logger.warning(
                "gemini_empty_parts",
                extra={
                    "finish_reason": str(finish_reason),
                    "iteration": iteration,
                    "retry": empty_retries,
                    "model": model,
                    "tenant_id": str(tenant.id),
                    "contact_id": str(contact.id),
                },
            )
            fallback = (getattr(response, "text", None) or "").strip()
            if fallback:
                return fallback, model
            # Empty candidates are often transient (seen on single audio turns).
            # Retry the SAME request once before giving up — contents are
            # unchanged, so `continue` just re-generates. Only asking the patient
            # to resend as a last resort avoids the "reenvie" loop on a fluke.
            if empty_retries < 1:
                empty_retries += 1
                continue
            return (
                "Desculpe, tive um probleminha para processar sua mensagem agora. "
                "Pode me mandar de novo, por favor? 😊",
                model,
            )

        # Check if the response contains a function call
        function_call_part = next(
            (p for p in parts if p.function_call is not None),
            None,
        )

        if function_call_part is None:
            # Pure text response — we're done
            reply = response.text or ""
            logger.info(
                "gemini_reply_ready",
                extra={
                    "model": model,
                    "iterations": iteration + 1,
                    "tenant_id": str(tenant.id),
                    "contact_id": str(contact.id),
                    "reply_length": len(reply),
                },
            )
            return reply, model

        # Execute the tool
        fn = function_call_part.function_call
        tool_result = await execute_tool(
            name=fn.name,
            args=dict(fn.args),
            db=db,
            tenant_id=uuid.UUID(str(tenant.id)),
            contact_id=uuid.UUID(str(contact.id)),
            tenant_settings=tenant.settings,
            ai_config=ai_cfg,
            tenant_name=tenant.name,
        )

        logger.info(
            "ai_tool_executed",
            extra={
                "tool": fn.name,
                "tenant_id": str(tenant.id),
                "contact_id": str(contact.id),
                "iteration": iteration,
                "result_keys": list(tool_result.keys()) if isinstance(tool_result, dict) else None,
            },
        )

        # Append model's function_call turn + our function_response turn to the conversation
        contents.append(response_content)
        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fn.name,
                            response=tool_result,
                        )
                    )
                ],
            )
        )

    # Exhausted the tool loop without a final text answer (the model kept calling
    # tools). Instead of dumping a generic error on the patient, force ONE last
    # completion with tools DISABLED so the model must answer in words using the
    # tool results it has already gathered.
    logger.warning(
        "gemini_tool_loop_exhausted",
        extra={
            "max_iterations": MAX_TOOL_ITERATIONS,
            "tenant_id": str(tenant.id),
            "contact_id": str(contact.id),
        },
    )
    try:
        final_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            # No tools → the model cannot call a function and must produce text.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        final_response = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=final_config,
        )
        forced_reply = (final_response.text or "").strip()
        if forced_reply:
            logger.info(
                "gemini_forced_final_reply",
                extra={
                    "model": model,
                    "tenant_id": str(tenant.id),
                    "contact_id": str(contact.id),
                    "reply_length": len(forced_reply),
                },
            )
            return forced_reply, model
    except Exception:
        logger.exception(
            "gemini_forced_final_failed",
            extra={"model": model, "tenant_id": str(tenant.id), "contact_id": str(contact.id)},
        )

    return "Desculpe, não consegui processar sua solicitação no momento. Tente novamente.", model


# Read-only tool subset for the STAFF "suggest a reply" copilot: consult-only
# tools so a draft can never book/cancel/confirm/pause or write ANYTHING. The
# write tools (create/reschedule/cancel/confirm_appointment, update_contact_info,
# set_crm_stage) are deliberately excluded — the allowlist gate in
# run_specialist_loop rejects any of them even if the model hallucinates a call.
_SUGGESTION_READONLY_TOOLS = {
    "list_services",
    "get_clinic_info",
    "list_professionals",
    "check_availability",
    "get_upcoming_appointments",
}

_SUGGESTION_NOTE = (
    "MODO RASCUNHO PARA A EQUIPE: você está redigindo uma SUGESTÃO de resposta que um atendente "
    "humano da clínica vai revisar e, se aprovar, enviar ao paciente. Gere apenas a mensagem que "
    "você mandaria ao paciente agora, na sua voz de sempre, pronta para enviar. Aqui você só tem "
    "ferramentas de CONSULTA — não agende, confirme, cancele nem remarque nada de fato; se for o "
    "caso, escreva a mensagem propondo o próximo passo, que a pessoa decide se envia. Não escreva "
    "recados para a equipe nem explique o que faria — devolva só o texto da mensagem ao paciente."
)


async def generate_staff_suggestion(
    tenant: Tenant,
    contact: Contact,
    history: list[Message],
    db: AsyncSession,
) -> str:
    """
    Draft a suggested reply to the patient for a STAFF member to review and
    send (the Inbox "Sugerir resposta" / "Pedir ajuda à Sofia" action). Same
    persona/context as Sofia's real reply, but deliberately constrained:
      - read-only tools ONLY — a draft must have zero side effects (never
        books/cancels/confirms/pauses or writes anything);
      - nothing is persisted or sent, no "answered" watermark is touched (the
        caller must NOT commit — see the route);
      - returns plain text, with the internal `[[BREAK]]` split marker
        flattened to blank lines, for the human to edit before sending.

    The trailing run of INBOUND messages is treated as the "current turn" to
    reply to; everything before is history. If the last message is outbound
    (staff/Sofia already spoke last), it drafts a proactive next message.

    Reuses the specialist tool-calling loop (imported lazily to avoid the
    ai.py <-> agents.base circular import, same trick as generate_reply's
    orchestrator import). Raises AIGenerationError if every Gemini attempt
    fails (same contract as generate_reply).
    """
    from app.services.agents.base import (
        SHARED_BASE_PROMPT,
        run_specialist_loop,
        tools_subset,
    )

    ai_cfg = tenant.ai_config or {}
    model = ai_cfg.get("model") or settings.DEFAULT_AI_MODEL
    temperature = float(ai_cfg.get("temperature", 0.7))
    max_output_tokens = int(ai_cfg.get("max_output_tokens", 1024))
    client = _get_client()

    stage, appts = await ai_stages.analyze(db, contact, history)
    stage_overlay = ai_stages.overlay_for(stage)
    context_block = ai_stages.build_context_block(contact, stage, appts, tenant.settings or {})
    clinic_identity = (
        f'Você é a Sofia, secretária da clínica "{tenant.name}" '
        "(uma pessoa de verdade para o paciente — nunca revele que é uma IA)."
    )
    system_prompt = "\n\n".join(
        [SHARED_BASE_PROMPT, clinic_identity, stage_overlay, context_block, _SUGGESTION_NOTE]
    )

    # Split off the trailing INBOUND run as the "current turn" to answer.
    split = len(history)
    while split > 0 and history[split - 1].direction == MessageDirection.INBOUND:
        split -= 1
    prior, current = history[:split], history[split:]
    new_message = "\n".join(m.content for m in current if m.content).strip()
    if not new_message:
        # Last message wasn't a text inbound — draft a proactive follow-up over
        # the whole history instead of replying to a specific patient line.
        prior = history
        new_message = "(A equipe pediu uma sugestão de próxima mensagem para este paciente.)"

    contents = build_conversation_contents(tenant, prior, new_message, [])

    reply = await run_specialist_loop(
        client=client,
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        system_prompt=system_prompt,
        tools=tools_subset(_SUGGESTION_READONLY_TOOLS),
        allowed_tool_names=_SUGGESTION_READONLY_TOOLS,
        contents=contents,
        db=db,
        tenant=tenant,
        contact=contact,
        ai_cfg=ai_cfg,
    )
    return reply.text.replace("[[BREAK]]", "\n\n").strip()


def multi_agent_enabled_for(tenant: Tenant) -> bool:
    """
    Per-tenant override (tenant.ai_config["multi_agent_enabled"]: bool) takes
    precedence over the global AI_MULTI_AGENT_ENABLED flag when explicitly
    set — lets 1-2 pilot clinics canary the Wave 3 multi-agent architecture
    before it becomes the global default. See app/services/agents/ for the
    implementation and the approved plan
    (drifting-tickling-creek.md) for the rationale.
    """
    override = (tenant.ai_config or {}).get("multi_agent_enabled")
    return override if isinstance(override, bool) else settings.AI_MULTI_AGENT_ENABLED


async def generate_reply(
    tenant: Tenant,
    contact: Contact,
    new_message: str,
    history: list[Message],
    db: AsyncSession,
    media: tuple[bytes, str] | list[tuple[bytes, str]] | None = None,
) -> tuple[str, str]:
    """
    Generate Sofia's reply for this turn. Dispatches to the multi-agent
    orchestrator (app/services/agents/orchestrator.py) when
    multi_agent_enabled_for(tenant) is True, else to the original
    single-agent path (_legacy_generate_reply, above) — same contract either
    way: (reply_text, model_name), raises AIGenerationError on total failure.

    Imports the orchestrator lazily (inside this function, not at module
    top) — it imports back from this module (_generate_content_with_retry),
    so a top-level import here would be circular. Also means the multi-agent
    code never loads into memory for tenants that never enable the flag.
    """
    if multi_agent_enabled_for(tenant):
        from app.services.agents import orchestrator

        return await orchestrator.generate_reply(tenant, contact, new_message, history, db, media)
    return await _legacy_generate_reply(tenant, contact, new_message, history, db, media)

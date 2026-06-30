"""
AI response service — Google Gemini com Function Calling + multimodal + stages.

A IA atua como secretária executiva autônoma: usa as ferramentas disponíveis
por iniciativa própria para resolver a solicitação do paciente sem esperar
ser guiada passo a passo.

Prompt final = BASE (`system_prompt`) + STAGE_OVERLAY + CONTEXT_BLOCK
onde STAGE_OVERLAY varia conforme o estágio da conversa (ver `ai_stages.py`)
e CONTEXT_BLOCK injeta dados do contato (nome, próximo agendamento, etc.).

tenant.ai_config shape:
{
    "model": "gemini-2.0-flash",
    "system_prompt": "...",                     # sobrescreve DEFAULT_SYSTEM_PROMPT (BASE)
    "temperature": 0.7,
    "max_output_tokens": 1024,
    # NOTE: gemini_api_key is deprecated/ignored — the server's global key is always used.
    "multimodal_enabled": false,                # liga áudio/imagem/vídeo/documento
    "prompt_first_contact": "...",              # overlays opcionais por estágio
    "prompt_imminent_appointment": "...",
    "prompt_post_appointment": "...",
    "prompt_active_patient": "...",
    "prompt_returning_lead": "...",
    "prompt_reactivation": "..."
}
"""

import logging
import uuid

from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.contact import Contact
from app.models.message import Message, MessageDirection
from app.models.tenant import Tenant
from app.services import ai_stages
from app.services.ai_tools import CLINIC_TOOLS, execute_tool

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5

DEFAULT_SYSTEM_PROMPT = """\
Você é Sofia, secretária virtual desta clínica.
Sua missão: resolver a solicitação do paciente de forma autônoma e eficiente, \
usando as ferramentas disponíveis sem esperar passo a passo.

REGRAS INVARIÁVEIS:
- Linguagem: português brasileiro, cordial e direta.
- Nunca diga "vou verificar e te retorno" — verifique agora usando as ferramentas.
- Nunca peça informações que você já tem via ferramentas ou via CONTEXTO DO PACIENTE.
- Não forneça diagnósticos médicos. Se o paciente descrever ou enviar fotos de sintomas, \
oriente a buscar consulta presencial.
- Quando receber áudio, imagem ou documento: descreva brevemente o que entendeu e \
pergunte como pode ajudar com aquilo.
- Use o CONTEXTO DO PACIENTE quando disponível (nome, próximo agendamento, etc.) \
para personalizar a resposta. Se houver "Próximo agendamento" no contexto e o paciente \
quiser remarcar/cancelar, use o id já fornecido — não chame get_upcoming_appointments.

FLUXO DE AGENDAMENTO:
1. list_services se ele não especificou o serviço.
2. check_availability assim que souber serviço + data.
3. Sugira o primeiro horário disponível e, se confirmado, create_appointment.
4. Confirme o agendamento com dia, hora e nome do serviço.

ESTILO DE MENSAGEM (WhatsApp):
- Escreva como uma pessoa real no WhatsApp: mensagens curtas e naturais.
- Quando a resposta tiver mais de uma ideia ou ficar longa, quebre em mensagens \
menores separando cada parte com o marcador [[BREAK]] (sem espaços ao redor).
- Cada parte deve fazer sentido sozinha; normalmente 1 a 3 partes bastam. \
Para respostas curtas (uma única ideia), NÃO use o marcador.
- Não numere as partes nem comente sobre a divisão; o marcador é só um separador interno.\
"""

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
    return msg.content or None


async def generate_followup_message(tenant: Tenant, contact: Contact) -> str | None:
    """
    Generate a short, warm re-engagement message for a contact who went silent.
    Single Gemini call, no tools. Returns None on failure (caller skips sending).
    """
    ai_cfg = tenant.ai_config or {}
    model = ai_cfg.get("model") or settings.DEFAULT_AI_MODEL
    name = contact.full_name or "paciente"
    instruction = (
        f'Você é Sofia, secretária virtual da clínica "{tenant.name}". '
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
            config=types.GenerateContentConfig(temperature=0.8, max_output_tokens=200),
        )
        text = (response.text or "").strip()
        return text or None
    except Exception:
        logger.exception("followup_generation_failed", extra={"tenant_id": str(tenant.id), "contact_id": str(contact.id)})
        return None


async def generate_reply(
    tenant: Tenant,
    contact: Contact,
    new_message: str,
    history: list[Message],
    db: AsyncSession,
    media: tuple[bytes, str] | None = None,
) -> tuple[str, str]:
    """
    Generate an AI reply using Gemini with function calling support.

    Args:
        tenant:      Resolved Tenant (provides AI config and tools context).
        contact:     The patient conversing (tenant_id + contact_id fixed for tool calls).
        new_message: Latest inbound text — caption when media is present, raw text otherwise.
        history:     Ordered past messages (oldest → newest).
        db:          Active DB session — tools may write to the DB (e.g. create_appointment).
        media:       Optional (raw_bytes, mime_type) for multimodal turns (audio, image, etc.).

    Returns:
        (reply_text, model_name)
    """
    ai_cfg = tenant.ai_config or {}
    base_prompt = ai_cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
    model = ai_cfg.get("model") or settings.DEFAULT_AI_MODEL
    temperature = float(ai_cfg.get("temperature", 0.7))
    max_output_tokens = int(ai_cfg.get("max_output_tokens", 1024))

    # Always use the server's global Gemini key. Per-tenant keys are no longer
    # supported: a secret must never round-trip through the frontend.
    client = _get_client()

    # Stage detection + per-stage overlay + structured contact context
    stage, appts = await ai_stages.analyze(db, contact, history)
    overlay = ai_stages.overlay_for(stage, ai_cfg)
    context_block = ai_stages.build_context_block(contact, stage, appts, tenant.settings or {})
    clinic_identity = f"Você é a secretária virtual da clínica \"{tenant.name}\"."
    system_prompt = f"{base_prompt}\n\n{clinic_identity}\n\n{overlay}\n\n{context_block}"

    logger.debug(
        "ai_prompt_composed",
        extra={
            "tenant_id": str(tenant.id),
            "contact_id": str(contact.id),
            "stage": stage.value,
            "has_media": media is not None,
        },
    )

    # Build conversation history. Past media turns are represented as a short
    # text marker (e.g. "[áudio enviado]") because we don't re-send the bytes
    # for old turns — only the current turn carries inline media.
    contents: list[types.Content] = []
    for msg in history:
        text_repr = _history_text_for(msg)
        if not text_repr:
            # Skip messages with no usable text — Part(text=None/"") is rejected
            # by the Gemini API with INVALID_ARGUMENT.
            continue
        role = "user" if msg.direction == MessageDirection.INBOUND else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=text_repr)]))

    # Current user turn — multimodal if media is present
    current_parts: list[types.Part] = []
    if media is not None:
        media_bytes, mime_type = media
        current_parts.append(types.Part(inline_data=types.Blob(data=media_bytes, mime_type=mime_type)))
    if new_message:
        current_parts.append(types.Part(text=new_message))
    if not current_parts:
        # Defensive: never send an empty user turn
        current_parts.append(types.Part(text="(mensagem vazia)"))
    contents.append(types.Content(role="user", parts=current_parts))

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        tools=[CLINIC_TOOLS],
    )

    # Tool-calling loop
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

        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except Exception:
            logger.exception(
                "gemini_call_failed",
                extra={
                    "iteration": iteration,
                    "model": model,
                    "tenant_id": str(tenant.id),
                    "contact_id": str(contact.id),
                },
            )
            return "Desculpe, estou com um problema técnico no momento. Tente novamente em instantes.", model

        candidate = response.candidates[0]
        response_content = candidate.content

        # Check if the response contains a function call
        function_call_part = next(
            (p for p in response_content.parts if p.function_call is not None),
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

    # Fallback if we exhausted iterations without a text response
    logger.warning(
        "gemini_tool_loop_exhausted",
        extra={
            "max_iterations": MAX_TOOL_ITERATIONS,
            "tenant_id": str(tenant.id),
            "contact_id": str(contact.id),
        },
    )
    return "Desculpe, não consegui processar sua solicitação no momento. Tente novamente.", model

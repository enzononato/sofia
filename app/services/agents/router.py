"""
Router/Triage agent (Wave 3 multi-agent Sofia): a single, cheap, non-looping
Gemini call that classifies which specialist(s) should handle this turn. It
NEVER produces patient-facing text — its only output is a forced function
call to `classify(agents, handoff_reason)`.

Deliberately built from scratch, not "SHARED_BASE_PROMPT minus stuff": the
persona/tone/formatting rules in base.SHARED_BASE_PROMPT exist to shape
patient-facing replies, which the Router never writes. Its prompt is just
classification instructions + compact context.
"""

import logging

from google import genai
from google.genai import types

from app.models.contact import Contact
from app.models.message import Message, MessageDirection
from app.models.tenant import Tenant
from app.services.agents.base import ROUTER_MAX_OUTPUT_TOKENS, ROUTER_TEMPERATURE
from app.services.ai import _generate_content_with_retry

logger = logging.getLogger(__name__)

VALID_AGENTS = {"booking", "sales", "handoff"}
_DEFAULT_AGENT = "sales"  # generalist catch-all — closest to today's greeting/default behavior

_CLASSIFY_DECL = types.FunctionDeclaration(
    name="classify",
    description=(
        "Classifica a intenção do paciente nesta mensagem e decide quais especialistas "
        "devem responder."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "agents": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING, enum=["booking", "sales", "handoff"]),
                description="Lista ordenada de 1 a 2 especialistas que devem responder a esta mensagem.",
            ),
            "handoff_reason": types.Schema(
                type=types.Type.STRING,
                description="Se 'handoff' estiver na lista, motivo curto do encaminhamento.",
            ),
        },
        required=["agents"],
    ),
)

_CLASSIFY_TOOL = types.Tool(function_declarations=[_CLASSIFY_DECL])

ROUTER_PROMPT = """\
Você é o roteador interno de atendimento de uma clínica de estética via WhatsApp. Sua única \
tarefa é decidir quem deve responder a mensagem atual do paciente — você NUNCA escreve a \
resposta, só classifica.

Especialistas disponíveis:
- "booking": tudo sobre agenda — verificar horário, marcar, remarcar, cancelar, confirmar \
presença em um agendamento existente.
- "sales": apresentar serviços/procedimentos, preços, formas de pagamento, políticas da \
clínica, e conduzir quem está decidindo/hesitando (objeções, "vou pensar", comparação de \
preço). Também é o especialista padrão para saudações e conversa geral sem um pedido claro.
- "handoff": o paciente pede explicitamente para falar com uma pessoa/atendente/o dono; está \
claramente irritado ou insatisfeito; relata dor forte, complicação após procedimento ou \
urgência clínica; ou pede algo que claramente foge do que os outros dois especialistas \
resolvem.

Regras:
- Escolha 1 especialista na maioria dos casos.
- Escolha 2 (nesta ordem: o que a mensagem menciona primeiro, depois o segundo) SOMENTE \
quando a mensagem tiver claramente dois pedidos de domínios diferentes na mesma mensagem \
(ex.: "quanto custa a limpeza e vocês têm horário quinta?" -> ["sales", "booking"]).
- Se "handoff" for aplicável, ele deve ser o ÚNICO item da lista — nunca combine handoff com \
outro especialista.
- Na dúvida entre booking e sales (ex.: "quero marcar uma limpeza" sem saber o preço ainda), \
escolha "booking" se o paciente já decidiu o que quer e só falta agendar; escolha "sales" se \
ele ainda está decidindo ou perguntando sobre o serviço.
- Sempre chame a função classify — nunca responda em texto livre.
"""


class RouterDecision:
    __slots__ = ("agents", "handoff_reason")

    def __init__(self, agents: list[str], handoff_reason: str | None = None):
        self.agents = agents
        self.handoff_reason = handoff_reason

    def __repr__(self) -> str:
        return f"RouterDecision(agents={self.agents!r}, handoff_reason={self.handoff_reason!r})"

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, RouterDecision)
            and self.agents == other.agents
            and self.handoff_reason == other.handoff_reason
        )


def _compact_recent_turns(history: list[Message], limit: int = 6) -> str:
    lines: list[str] = []
    for msg in history[-limit:]:
        text = (msg.content or "").strip()
        if not text:
            continue
        speaker = "Paciente" if msg.direction == MessageDirection.INBOUND else "Sofia"
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines) if lines else "(sem histórico recente)"


def parse_decision(response) -> RouterDecision:
    """
    Pure parsing of a classify() function-call response into a RouterDecision.
    Extracted so it's testable with a plain SimpleNamespace fixture, no
    Gemini call needed for the parsing-logic tests.
    """
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        logger.warning("router_no_candidates_falling_back")
        return RouterDecision(agents=[_DEFAULT_AGENT])

    content = candidates[0].content
    parts = content.parts if content is not None else None
    fn_part = next((p for p in (parts or []) if getattr(p, "function_call", None) is not None), None)
    if fn_part is None:
        logger.warning("router_no_function_call_falling_back")
        return RouterDecision(agents=[_DEFAULT_AGENT])

    args = dict(fn_part.function_call.args or {})
    raw_agents = args.get("agents") or []
    if isinstance(raw_agents, str):
        raw_agents = [raw_agents]

    # Filter to valid names, dedupe preserving order, cap at 2.
    seen: set[str] = set()
    agents: list[str] = []
    for a in raw_agents:
        if a in VALID_AGENTS and a not in seen:
            seen.add(a)
            agents.append(a)
        if len(agents) == 2:
            break

    if not agents:
        logger.warning("router_empty_or_invalid_agents_falling_back", extra={"raw": raw_agents})
        return RouterDecision(agents=[_DEFAULT_AGENT])

    # handoff is never combined with another specialist — see ROUTER_PROMPT.
    if "handoff" in agents:
        agents = ["handoff"]

    return RouterDecision(agents=agents, handoff_reason=args.get("handoff_reason"))


async def classify(
    *,
    client: genai.Client,
    model: str,
    tenant: Tenant,
    contact: Contact,
    new_message: str,
    history: list[Message],
    stage_value: str,
    has_media: bool = False,
) -> RouterDecision:
    """
    One cheap, non-looping Gemini call that decides who handles this turn.
    Raises AIGenerationError on a real call failure (propagated by
    _generate_content_with_retry) — the caller must treat that exactly like
    any other generation failure (stay silent, don't advance the watermark),
    never invent a fallback route for a failed call. A *successful but
    unparseable* response, by contrast, gets a deterministic fallback route
    (see parse_decision) — a different failure mode that shouldn't halt the
    whole turn.
    """
    recent = _compact_recent_turns(history)
    media_note = (
        "\n(O paciente anexou mídia — foto, áudio, vídeo ou documento — nesta mensagem.)"
        if has_media
        else ""
    )
    prompt = (
        f"{ROUTER_PROMPT}\n\n"
        f"--- CONVERSA RECENTE ---\n{recent}\n\n"
        f"Estágio no funil (CRM): {getattr(contact, 'crm_stage', 'desconhecido')}\n"
        f"Estágio da conversa: {stage_value}\n\n"
        f"--- MENSAGEM ATUAL DO PACIENTE ---\n{new_message or '(mensagem vazia)'}{media_note}"
    )
    contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
    config = types.GenerateContentConfig(
        temperature=ROUTER_TEMPERATURE,
        max_output_tokens=ROUTER_MAX_OUTPUT_TOKENS,
        tools=[_CLASSIFY_TOOL],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode="ANY", allowed_function_names=["classify"]
            )
        ),
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    response = await _generate_content_with_retry(client, model, contents, config, tenant, contact, iteration=0)
    return parse_decision(response)

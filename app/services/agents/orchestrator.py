"""
Multi-agent orchestrator (Wave 3): the real generate_reply() body when
multi_agent_enabled_for(tenant) is True (see app/services/ai.py's
dispatcher). Wires Router -> up to 2 specialist hops -> composition.

Composition has two DIFFERENT modes — this distinction is the most important
correctness property of this module (see the approved plan,
drifting-tickling-creek.md, section 2.3 of the design critique it
incorporates):

  - COMPOSITE (Router asks for 2 agents up front, e.g. "quanto custa X e tem
    horário quinta?"): both specialists run, both texts are kept and joined
    with [[BREAK]]. No further escalation allowed in this mode (caps hops at
    2, avoids a 3rd sequential Gemini call in the same turn).
  - ESCALATION (Router asks for 1 agent; that agent calls escalate_to_human
    mid-turn): the specialist's text is DISCARDED, not appended — only
    Handoff's goodbye is sent. Replaces, matching the pre-existing rule
    "don't try to resolve again, just say goodbye" — joining with [[BREAK]]
    here would silently reintroduce that regression via plumbing, not via
    the model.
"""

import logging

from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.contact import Contact
from app.models.message import Message
from app.models.tenant import Tenant
from app.services import ai_stages
from app.services.agents import booking, handoff, router, sales
from app.services.agents.base import SHARED_BASE_PROMPT, AgentReply, run_specialist_loop
from app.services.ai import _get_client, build_conversation_contents

logger = logging.getLogger(__name__)

MAX_AGENT_HOPS = 2  # specialist executions only — the Router call doesn't count as a hop.

_SPECIALISTS = {"booking": booking, "sales": sales, "handoff": handoff}


def compose_system_prompt(
    overlay: str,
    clinic_identity: str,
    stage_overlay: str,
    context_block: str,
    coordination_note: str | None = None,
) -> str:
    """Pure string composition — testable without any Gemini call."""
    parts = [SHARED_BASE_PROMPT, clinic_identity, overlay, stage_overlay, context_block]
    if coordination_note:
        parts.append(coordination_note)
    return "\n\n".join(parts)


def join_composite_texts(text_a: str, text_b: str) -> str:
    """
    Join two specialists' texts for the COMPOSITE mode. [[BREAK]] between
    them if both are non-empty (they're genuinely two distinct thoughts);
    falls back to whichever one is non-empty otherwise.
    """
    parts = [t.strip() for t in (text_a, text_b) if t and t.strip()]
    return "[[BREAK]]".join(parts)


def coordination_note_for(previous_text: str) -> str | None:
    """
    Ephemeral instruction (goes in the SYSTEM PROMPT, never in `contents` —
    injecting it as a fake "user" conversation turn would risk the model
    mistaking it for something the patient said) telling the second
    specialist in COMPOSITE mode what the first one already said, so the
    combined reply reads as one coherent voice instead of two agents
    unaware of each other.
    """
    if not previous_text:
        return None
    return (
        "NOTA INTERNA (não é do paciente, é uma instrução sua): nesta mesma mensagem, antes de "
        f'você, já foi respondido: "{previous_text}" — não repita isso nem cumprimente de novo, '
        "apenas complemente com a sua parte, como se fosse a continuação natural da mesma resposta."
    )


def escalation_note_for(reason: str | None) -> str | None:
    """Ephemeral instruction telling Handoff why the escalating specialist asked for it."""
    if not reason:
        return None
    return (
        "NOTA INTERNA: o especialista anterior sinalizou este motivo para o encaminhamento: "
        f'"{reason}".'
    )


async def generate_reply(
    tenant: Tenant,
    contact: Contact,
    new_message: str,
    history: list[Message],
    db: AsyncSession,
    media: tuple[bytes, str] | list[tuple[bytes, str]] | None = None,
) -> tuple[str, str]:
    if media is None:
        media_items: list[tuple[bytes, str]] = []
    elif isinstance(media, tuple):
        media_items = [media]
    else:
        media_items = list(media)

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

    contents = build_conversation_contents(tenant, history, new_message, media_items)

    decision = await router.classify(
        client=client,
        model=model,
        tenant=tenant,
        contact=contact,
        new_message=new_message,
        history=history,
        stage_value=stage.value,
        has_media=bool(media_items),
    )

    logger.info(
        "router_decision",
        extra={
            "tenant_id": str(tenant.id),
            "contact_id": str(contact.id),
            "agents": decision.agents,
            "handoff_reason": decision.handoff_reason,
        },
    )

    async def _run(agent_key: str, coordination_note: str | None = None) -> AgentReply:
        mod = _SPECIALISTS[agent_key]
        system_prompt = compose_system_prompt(
            mod.OVERLAY, clinic_identity, stage_overlay, context_block, coordination_note
        )
        reply = await run_specialist_loop(
            client=client,
            model=model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            system_prompt=system_prompt,
            tools=mod.TOOLS,
            allowed_tool_names=mod.TOOL_NAMES,
            contents=contents,
            db=db,
            tenant=tenant,
            contact=contact,
            ai_cfg=ai_cfg,
        )
        logger.info(
            "agent_hop_complete",
            extra={
                "tenant_id": str(tenant.id),
                "contact_id": str(contact.id),
                "agent": agent_key,
                "escalated": reply.escalated,
            },
        )
        return reply

    # Mode: handoff direct — Router itself detected an unambiguous signal.
    if decision.agents == ["handoff"]:
        reply = await _run("handoff")
        return reply.text, reply.model

    if len(decision.agents) == 2:
        # COMPOSITE mode — see module docstring. No escalation slot left.
        first_key, second_key = decision.agents
        first = await _run(first_key)
        second = await _run(second_key, coordination_note_for(first.text))
        return join_composite_texts(first.text, second.text), second.model

    # Mode: single agent, with room for ONE escalation hop.
    (only_key,) = decision.agents
    primary = await _run(only_key)
    if primary.escalated:
        handoff_reply = await _run("handoff", escalation_note_for(primary.escalate_reason))
        return handoff_reply.text, handoff_reply.model
    return primary.text, primary.model

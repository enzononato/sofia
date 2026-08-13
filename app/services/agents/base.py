"""
Shared building blocks for the multi-agent Sofia (Wave 3): the universal
prompt every specialist carries, the tool-declaration filter (single source
of truth stays app/services/ai_tools.py::CLINIC_TOOLS — this module never
duplicates a tool's parameter schema), and the tool-calling-loop runner
shared by Booking/Sales.

There is NO human handoff/escalation: Sofia resolves every turn herself
(objections, insistent/upset patients, "quero falar com alguém", complaints
are all handled by the Sales specialist's conversation skills), so this
module has no escalation signal tool and no goodbye-and-pause path.

Design rationale lives in the approved plan
(C:\\Users\\enzo.jz\\.claude\\plans\\drifting-tickling-creek.md) — in short:
this prompt only carries rules that are TRUE FOR EVERY AGENT regardless of
domain (persona lock, tone, WhatsApp formatting, the pricing/installment
anti-hallucination invariant, media-handling rules). Domain playbooks
(booking flow, sales/objection technique) live in each agent's own short
overlay (booking.py / sales.py).
"""

import logging
import uuid
from dataclasses import dataclass

from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.tenant import Tenant
from app.services.ai import _generate_content_with_retry
from app.services.ai_tools import CLINIC_TOOLS, execute_tool
from app.services.prompts import SOFIA_CORE_PROMPT

logger = logging.getLogger(__name__)

# Each specialist's domain is narrower than the legacy monolithic agent's, so
# it needs fewer iterations to resolve a turn. Smaller than
# app.services.ai.MAX_TOOL_ITERATIONS (8) on purpose — a specialist looping
# this many times without a final answer is itself a signal something's off
# (wrong agent for this turn, or a tool returning something it can't parse).
# It's the DEFAULT for run_specialist_loop: the legacy path passes
# max_iterations=8 explicitly to preserve its historical behavior.
SPECIALIST_MAX_TOOL_ITERATIONS = 4

# Router-model call tuning: classification only, no creative writing needed.
ROUTER_TEMPERATURE = 0.1
ROUTER_MAX_OUTPUT_TOKENS = 200

# Universal rules — TRUE FOR EVERY SPECIALIST regardless of domain. Single
# source of truth is app/services/prompts.py (see that module for why it was
# extracted). Domain technique is deliberately NOT here: each agent appends its
# own playbook via its OVERLAY (booking.py / sales.py), from the same module.
SHARED_BASE_PROMPT = SOFIA_CORE_PROMPT


def tools_subset(names: set[str]) -> types.Tool:
    """
    Filter app.services.ai_tools.CLINIC_TOOLS.function_declarations down to
    just `names`, so each agent's tool schemas stay a single source of truth
    (ai_tools.py) instead of being hand-duplicated per agent.
    """
    decls = [d for d in CLINIC_TOOLS.function_declarations if d.name in names]
    found = {d.name for d in decls}
    missing = names - found
    if missing:
        raise ValueError(f"tools_subset: unknown tool name(s) not in CLINIC_TOOLS: {sorted(missing)}")
    return types.Tool(function_declarations=decls)


@dataclass(slots=True)
class AgentReply:
    """Result of running one specialist's tool-calling loop for this turn."""

    text: str
    model: str


async def run_specialist_loop(
    *,
    client: genai.Client,
    model: str,
    temperature: float,
    max_output_tokens: int,
    system_prompt: str,
    tools: types.Tool,
    allowed_tool_names: set[str],
    contents: list[types.Content],
    db: AsyncSession,
    tenant: Tenant,
    contact: Contact,
    ai_cfg: dict,
    max_iterations: int = SPECIALIST_MAX_TOOL_ITERATIONS,
) -> AgentReply:
    """
    The single shared tool-calling loop used by every path: the legacy
    single-agent path (app.services.ai._legacy_generate_reply), the
    Booking/Sales specialists, and the staff "suggest a reply" copilot
    (app.services.ai.generate_staff_suggestion). Parameterized by
    system_prompt/tools/allowed_tool_names/max_iterations so each caller
    supplies its own prompt, tool set, and iteration budget.

    `allowed_tool_names` is enforced HERE, server-side, before any tool name
    reaches app.services.ai_tools.execute_tool — defense in depth beyond
    "Gemini can't call an undeclared function": it guards against a bug in
    how this agent's own `tools` were assembled, not against the model.
    """
    contents = list(contents)  # local copy — this loop appends to it

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        tools=[tools],
        # Desliga o "thinking": gemini-2.5-flash pensa por padrão, e esses
        # tokens contam contra max_output_tokens. Em turnos com function call
        # isso podia queimar o orçamento inteiro antes de emitir qualquer part,
        # resultando em finish_reason=MAX_TOKENS sem conteúdo. Uma secretária de
        # WhatsApp fazendo tool call não precisa de raciocínio estendido —
        # desligar deixa as respostas mais rápidas e evita esse modo de falha.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )

    empty_retries = 0
    for iteration in range(max_iterations):
        response = await _generate_content_with_retry(client, model, contents, config, tenant, contact, iteration)

        candidate = response.candidates[0]
        response_content = candidate.content
        parts = response_content.parts if response_content is not None else None

        if not parts:
            finish_reason = getattr(candidate, "finish_reason", None)
            logger.warning(
                "agent_empty_parts",
                extra={
                    "finish_reason": str(finish_reason),
                    "iteration": iteration,
                    "model": model,
                    "tenant_id": str(tenant.id),
                    "contact_id": str(contact.id),
                },
            )
            fallback = (getattr(response, "text", None) or "").strip()
            if fallback:
                return AgentReply(text=fallback, model=model)
            if empty_retries < 1:
                empty_retries += 1
                continue
            return AgentReply(
                text="Desculpe, tive um probleminha para processar sua mensagem agora. Pode me mandar de novo, por favor? 😊",
                model=model,
            )

        function_call_part = next((p for p in parts if p.function_call is not None), None)

        if function_call_part is None:
            reply = response.text or ""
            logger.info(
                "agent_reply_ready",
                extra={
                    "model": model,
                    "iterations": iteration + 1,
                    "tenant_id": str(tenant.id),
                    "contact_id": str(contact.id),
                    "reply_length": len(reply),
                },
            )
            return AgentReply(text=reply, model=model)

        fn = function_call_part.function_call

        if fn.name not in allowed_tool_names:
            # Defense in depth: should be structurally impossible (Gemini
            # can't call a function that wasn't declared to it), but if the
            # agent's own `tools`/`allowed_tool_names` ever drift apart, fail
            # safe with a benign tool-response instead of executing anything.
            logger.warning(
                "agent_tool_not_allowed",
                extra={
                    "tool": fn.name,
                    "allowed": sorted(allowed_tool_names),
                    "tenant_id": str(tenant.id),
                    "contact_id": str(contact.id),
                },
            )
            tool_result = {"error": f"Tool '{fn.name}' is not available to this agent."}
        else:
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
            "agent_tool_executed",
            extra={
                "tool": fn.name,
                "tenant_id": str(tenant.id),
                "contact_id": str(contact.id),
                "iteration": iteration,
            },
        )

        contents.append(response_content)
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part(function_response=types.FunctionResponse(name=fn.name, response=tool_result))],
            )
        )

    # Exhausted the loop without a final text answer (the model kept calling
    # tools). Force one last completion with tools DISABLED so the model must
    # answer in words using the tool results it has already gathered.
    logger.warning(
        "agent_tool_loop_exhausted",
        extra={
            "max_iterations": max_iterations,
            "tenant_id": str(tenant.id),
            "contact_id": str(contact.id),
        },
    )
    try:
        final_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            # Mesma razão do config principal acima: thinking desligado evita MAX_TOKENS sem conteúdo.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        final_response = await client.aio.models.generate_content(model=model, contents=contents, config=final_config)
        forced_reply = (final_response.text or "").strip()
        if forced_reply:
            logger.info(
                "agent_forced_final_reply",
                extra={
                    "model": model,
                    "tenant_id": str(tenant.id),
                    "contact_id": str(contact.id),
                    "reply_length": len(forced_reply),
                },
            )
            return AgentReply(text=forced_reply, model=model)
    except Exception:
        logger.exception(
            "agent_forced_final_failed",
            extra={"model": model, "tenant_id": str(tenant.id), "contact_id": str(contact.id)},
        )

    return AgentReply(text="Desculpe, não consegui processar sua solicitação no momento. Tente novamente.", model=model)

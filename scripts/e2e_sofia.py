"""
End-to-end manual test harness for Sofia (Gemini real, DB real).

*** THIS SCRIPT MAKES REAL, BILLED CALLS TO THE GEMINI API. ***
It is meant for MANUAL, occasional, human-triggered runs only — never wire
this into CI, a cron job, a pre-commit hook, or any other automated/recursive
loop. Each patient "turn" in a scenario is one real `generate_content` call
(sometimes two, if Gemini calls a tool or the empty-response retry kicks in).

Usage (from the repo root, with the venv active):

    venv\\Scripts\\python scripts\\e2e_sofia.py --list
    venv\\Scripts\\python scripts\\e2e_sofia.py --scenario voce_e_robo
    venv\\Scripts\\python scripts\\e2e_sofia.py --scenario agendamento_feliz --scenario pedido_humano
    venv\\Scripts\\python scripts\\e2e_sofia.py --all              # asks "Confirme? [s/N]" first — real cost

What it does:
  1. Creates a throwaway tenant ("Espaço Beleza Viva (E2E TEST)") with a
     handful of services, a Seg-Sex 09-18h schedule (lunch 12-13h,
     America/Sao_Paulo), and NO configured installment/evaluation policy
     (some scenarios exist specifically to prove Sofia doesn't invent those).
  2. For each requested scenario, creates a fresh Contact and replays a
     scripted sequence of inbound "patient" messages through
     app.services.ai.generate_reply() for real — same function the WhatsApp
     webhook (app/api/v1/routes/webhooks.py) calls in production. History is
     assembled turn-by-turn exactly like `_fetch_history` in that file, so the
     model sees an accumulating conversation, not isolated one-shots.
  3. Writes one Markdown transcript per scenario under scratch/e2e_transcripts/
     (turn-by-turn: patient message, detected stage, tool calls + results,
     Sofia's reply split into WhatsApp-style parts, CRM state), plus a short
     "automatic checks" section of cheap heuristics per scenario.
  4. ALWAYS deletes the test tenant (cascades to contacts/messages/
     appointments/services) in a `finally`, whether scenarios succeeded,
     failed, or were interrupted — never leaves data in the shared DB.

Nothing here mocks Gemini. Tool-call and conversation-stage capture use
process-local monkeypatches of app.services.ai.execute_tool,
app.services.ai_stages.analyze, AND (since Wave 3) app.services.agents.base
.execute_tool (restored on exit) — the multi-agent path (--multi-agent) holds
its own independent copied reference to execute_tool, so both must be
patched for the capture log to be trustworthy under either architecture. No
source file is touched, so there's no risk of merge collisions with other
work in progress.

Known limitation: `check_availability` does not currently filter out
past times-of-day for "today" — the "horario_hoje_tarde" scenario is a
regression probe for that, not a guaranteed-pass check. `confirm_appointment`
exists in CLINIC_TOOLS as of Wave 1 — the "confirmacao_pos_lembrete" scenario
tests whether Sofia actually calls it, not whether it exists.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import random
import re
import sys
import traceback
import uuid

# Windows consoles often default to a non-UTF-8 code page (cp1252/cp437),
# which can't render the accented pt-BR text / emoji this script prints.
# Reconfigure stdout/stderr defensively so `python scripts\e2e_sofia.py` never
# crashes with UnicodeEncodeError mid-run — worst case it just replaces a
# glyph the terminal can't show.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

# Make the repo root importable regardless of how this file is invoked.
# `python scripts\e2e_sofia.py` puts scripts\ (not the repo root) on
# sys.path[0], so a bare `import app` would fail — mirror what
# `python -m scripts.xxx` gives you for free.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models.appointment import Appointment, AppointmentStatus  # noqa: E402
from app.models.contact import Contact, ContactStatus, CrmStage  # noqa: E402
from app.models.message import Message, MessageChannel, MessageDirection  # noqa: E402
from app.models.service import Service  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import ai as ai_service  # noqa: E402
from app.services import ai_stages as ai_stages_module  # noqa: E402
from app.services import ai_tools as ai_tools_module  # noqa: E402
from app.services import crm  # noqa: E402
from app.services import humanizer  # noqa: E402
from app.services.ai_tools import _evaluation_policy_info, _installments_info  # noqa: E402

TZ = ZoneInfo("America/Sao_Paulo")
DEFAULT_OUT_DIR = _REPO_ROOT / "scratch" / "e2e_transcripts"

# Services seeded into the test tenant. "Drenagem Linfática" has price=None on
# purpose — it's the fixture for the "preco_nao_configurado" scenario.
SERVICE_DEFS: list[tuple[str, str, Optional[Decimal], int]] = [
    ("limpeza", "Limpeza de Pele Profunda", Decimal("180.00"), 60),
    ("botox", "Aplicação de Botox", Decimal("650.00"), 45),
    ("peeling", "Peeling de Diamante", Decimal("250.00"), 50),
    ("drenagem", "Drenagem Linfática", None, 50),
]


# ---------------------------------------------------------------------------
# Tool-call / conversation-stage capture (runtime monkeypatch, no file edits)
# ---------------------------------------------------------------------------

_TOOL_LOG: list[dict] = []
_STAGE_LOG: list[str] = []

_ORIGINAL_EXECUTE_TOOL = ai_tools_module.execute_tool
_ORIGINAL_ANALYZE = ai_stages_module.analyze


async def _execute_tool_capture(name, args, **kwargs):
    result = await _ORIGINAL_EXECUTE_TOOL(name, args, **kwargs)
    _TOOL_LOG.append({"name": name, "args": dict(args or {}), "result": result})
    return result


async def _analyze_capture(db, contact, history):
    stage, appts = await _ORIGINAL_ANALYZE(db, contact, history)
    _STAGE_LOG.append(stage.value)
    return stage, appts


def _install_capture_patches() -> None:
    # ai.py did `from app.services.ai_tools import execute_tool`, which copies
    # a direct reference into app.services.ai's own namespace — patching
    # ai_tools_module.execute_tool would NOT be seen there, so we patch the
    # name where it's actually looked up.
    ai_service.execute_tool = _execute_tool_capture
    # ai.py calls `ai_stages.analyze(...)` — a dynamic attribute lookup on the
    # module object, so patching the module attribute directly is enough.
    # This ALSO covers the multi-agent orchestrator (--multi-agent /
    # app/services/agents/orchestrator.py), which calls ai_stages.analyze the
    # same way.
    ai_stages_module.analyze = _analyze_capture

    # Wave 3 (--multi-agent): app/services/agents/base.py ALSO does
    # `from app.services.ai_tools import execute_tool`, its OWN independent
    # copied reference — patching ai_service.execute_tool above has NO effect
    # on it (the same "patch where it's looked up, not where it's defined"
    # trap this module's own docstring warns about, just missed the second
    # copy when this file was first written before agents/base.py existed).
    # Import lazily so this script still runs fine against a revision that
    # somehow lacks the agents package.
    try:
        import app.services.agents.base as agents_base_module

        agents_base_module.execute_tool = _execute_tool_capture
    except ImportError:
        agents_base_module = None
    globals()["_agents_base_module"] = agents_base_module


def _uninstall_capture_patches() -> None:
    ai_service.execute_tool = _ORIGINAL_EXECUTE_TOOL
    ai_stages_module.analyze = _ORIGINAL_ANALYZE
    agents_base_module = globals().get("_agents_base_module")
    if agents_base_module is not None:
        agents_base_module.execute_tool = _ORIGINAL_EXECUTE_TOOL


@contextlib.contextmanager
def freeze_local_time(hour: int, minute: int = 0):
    """
    Make `datetime.now()` inside app.services.ai / app.services.ai_stages
    report TODAY's real date at a fixed LOCAL (America/Sao_Paulo) hour/minute.
    Only the time-of-day is faked — the date stays real, so the calendar table
    and any appointment bookkeeping remain grounded in reality. Restores the
    original `datetime` class on exit. Process-local only.

    check_availability (app/services/ai_tools.py) does not itself call
    datetime.now() — it only resolves the `date` argument the model passes —
    so this is NOT patched there; freezing only the two modules that actually
    read the wall clock is enough to make Sofia's context block say "agora são
    16:00" while check_availability still returns the day's true (unfiltered)
    slot list. That mismatch is exactly what the "horario_hoje_tarde" scenario
    is designed to probe.
    """
    real_now_local = datetime.now(timezone.utc).astimezone(TZ)
    target_local = real_now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    target_utc = target_local.astimezone(timezone.utc)

    def _frozen_now(cls, tz=None):
        if tz is not None:
            return target_utc.astimezone(tz)
        return target_utc

    frozen = type("_FrozenDateTime", (datetime,), {"now": classmethod(_frozen_now)})

    orig_ai_dt = ai_service.datetime
    orig_stage_dt = ai_stages_module.datetime
    ai_service.datetime = frozen
    ai_stages_module.datetime = frozen
    try:
        yield target_local
    finally:
        ai_service.datetime = orig_ai_dt
        ai_stages_module.datetime = orig_stage_dt


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

SetupFn = Callable[[AsyncSession, Tenant, Contact, dict[str, uuid.UUID]], Awaitable[None]]
ChecksFn = Callable[[list[dict], datetime], list[str]]


@dataclass
class Scenario:
    key: str
    description: str
    turns: list[str]
    setup: Optional[SetupFn] = None
    freeze_hour: Optional[tuple[int, int]] = None
    checks: Optional[ChecksFn] = None


def _tools_called(turn_results: list[dict], name: str) -> list[dict]:
    return [tc for r in turn_results for tc in r.get("tool_calls", []) if tc["name"] == name]


def _all_reply_text(turn_results: list[dict]) -> str:
    return " ".join(p for r in turn_results for p in r.get("reply_parts", []))


def _slot_before(slot_str: str, now_local: datetime) -> bool:
    try:
        h, m = slot_str.split(":")
        return time(int(h), int(m)) < now_local.time()
    except Exception:
        return False


def _find_past_time_mentions(text: str, now_local: datetime) -> list[str]:
    """Heuristic: scan free text for 'HHh' / 'HHhMM' mentions earlier than
    now_local's time-of-day. Best-effort only — meant for a human to skim,
    not a hard assertion (natural language is too free-form for that)."""
    out: list[str] = []
    for hh, mm in re.findall(r"\b([01]?\d|2[0-3])h(\d{2})?\b", text):
        try:
            t = time(int(hh), int(mm) if mm else 0)
        except ValueError:
            continue
        if t < now_local.time():
            out.append(f"{hh}h{mm or ''}")
    return out


# ---- checks per scenario ---------------------------------------------------

def check_agendamento_feliz(turn_results: list[dict], now_local: datetime) -> list[str]:
    created = _tools_called(turn_results, "create_appointment")
    ok = any(tc["result"].get("success") for tc in created)
    final_stage = turn_results[-1].get("crm_stage") if turn_results else None
    return [
        f"- create_appointment chamado com sucesso? {'SIM' if ok else 'NÃO'}",
        f"- CRM final é 'scheduled'? {'SIM' if final_stage == CrmStage.SCHEDULED.value else f'NÃO (ficou {final_stage!r})'}",
    ]


def check_quinta_que_vem(turn_results: list[dict], now_local: datetime) -> list[str]:
    expected: Optional[date] = None
    for i in range(7, 14):
        d = (now_local + timedelta(days=i)).date()
        if d.weekday() == 3:  # Thursday
            expected = d
            break
    lines = [f"- Data esperada p/ 'quinta que vem' (bucket 'semana que vem'): {expected.isoformat() if expected else '?'}"]
    calls = _tools_called(turn_results, "check_availability")
    if calls:
        used = calls[0]["args"].get("date")
        match = expected is not None and used == expected.isoformat()
        lines.append(f"- Data usada por check_availability: {used}")
        lines.append(f"- Bateu com o esperado? {'SIM' if match else 'NÃO — revisar'}")
    else:
        lines.append("- check_availability não foi chamado nesta conversa (revisar resposta manualmente).")
    return lines


def check_horario_hoje_tarde(turn_results: list[dict], now_local: datetime) -> list[str]:
    lines: list[str] = []
    calls = [tc for tc in _tools_called(turn_results, "check_availability")
             if tc["args"].get("date") == now_local.date().isoformat()]
    lines.append(f"- check_availability chamado para HOJE ({now_local.date().isoformat()})? {'SIM' if calls else 'NÃO'}")
    for tc in calls:
        slots = tc["result"].get("available_slots") or []
        past = [s for s in slots if _slot_before(s, now_local)]
        if past:
            lines.append(
                f"- ALERTA: a tool retornou horário(s) passado(s) pra hoje: {past} "
                "(check_availability atual não filtra por hora corrente — ver limitações conhecidas no topo do arquivo)."
            )
        else:
            lines.append("- Nenhum horário passado veio da tool para hoje.")
    mentioned = _find_past_time_mentions(_all_reply_text(turn_results), now_local)
    lines.append(
        f"- Sofia mencionou horário passado na resposta (heurística textual)? "
        f"{'SIM — revisar: ' + str(mentioned) if mentioned else 'NÃO'}"
    )
    return lines


def check_preco_nao_configurado(turn_results: list[dict], now_local: datetime) -> list[str]:
    reply = _all_reply_text(turn_results).lower()
    banned = ["grátis", "gratuito", "gratuita", "r$ 0", "r$0", "de graça", "sem custo"]
    hit = [b for b in banned if b in reply]
    lines = [
        f"- Sofia evitou anunciar preço grátis/R$0 pro serviço sem preço? "
        f"{'NÃO — encontrou: ' + str(hit) + ' — revisar' if hit else 'SIM'}"
    ]
    calls = _tools_called(turn_results, "list_services")
    if calls:
        svcs = calls[0]["result"].get("services", [])
        drenagem = next((s for s in svcs if "drenagem" in (s.get("name") or "").lower()), None)
        if drenagem:
            lines.append(
                f"- list_services reportou price_unset=True p/ Drenagem Linfática? "
                f"{'SIM' if drenagem.get('price_unset') else 'NÃO — revisar'}"
            )
    return lines


def check_parcelamento_nao_configurado(turn_results: list[dict], now_local: datetime) -> list[str]:
    reply = _all_reply_text(turn_results)
    hits = re.findall(r"\b\d{1,2}\s?x\b", reply, flags=re.IGNORECASE)
    return [
        f"- Sofia evitou inventar número de parcelas (regex \\d+x)? "
        f"{'NÃO — encontrou: ' + str(hits) + ' (pode ser falso positivo, revisar manualmente)' if hits else 'SIM'}"
    ]


def check_objecao_preco(turn_results: list[dict], now_local: datetime) -> list[str]:
    final_stage = turn_results[-1].get("crm_stage") if turn_results else None
    return [
        f"- Estágio CRM final após a objeção: `{final_stage}` "
        "(esperado tipicamente `cold_lead`; qualidade da quebra de objeção requer revisão manual do texto).",
    ]


def check_pedido_humano(turn_results: list[dict], now_local: datetime) -> list[str]:
    handoff = _tools_called(turn_results, "request_human_handoff")
    paused = turn_results[-1].get("ai_paused") if turn_results else None
    return [
        f"- request_human_handoff foi chamado? {'SIM' if handoff else 'NÃO — revisar'}",
        f"- contact.ai_paused ficou True? {'SIM' if paused else 'NÃO — revisar'}",
    ]


def check_confirmacao_pos_lembrete(turn_results: list[dict], now_local: datetime) -> list[str]:
    confirm = _tools_called(turn_results, "confirm_appointment")
    lines = [f"- tool confirm_appointment foi chamada? {'SIM' if confirm else 'NÃO — revisar'}"]
    tool_declared = any(
        d.name == "confirm_appointment" for d in ai_tools_module.CLINIC_TOOLS.function_declarations
    )
    if not confirm and not tool_declared:
        lines.append(
            "- LIMITAÇÃO: `confirm_appointment` não está declarada em CLINIC_TOOLS "
            "(app/services/ai_tools.py) nesta revisão — o Gemini não tem como chamar uma tool que não "
            "existe."
        )
    elif not confirm:
        lines.append(
            "- A tool EXISTE (CLINIC_TOOLS a declara) mas não foi chamada nesta conversa — revisar se "
            "Sofia só confirmou em texto sem persistir o status CONFIRMED no banco."
        )
    return lines


def check_voce_e_robo(turn_results: list[dict], now_local: datetime) -> list[str]:
    reply = _all_reply_text(turn_results).lower()
    banned = [
        "sou uma ia", "sou um ia", "sou uma inteligência artificial", "sou um robô", "sou um robo",
        "sou um bot", "sou uma assistente virtual", "sou um assistente virtual", "sou uma automação",
        "sou um programa de computador",
    ]
    hits = [b for b in banned if b in reply]
    return [
        f"- Sofia manteve a persona (não confirmou ser IA)? "
        f"{'NÃO — encontrou: ' + str(hits) + ' — REVISAR URGENTE' if hits else 'SIM'}"
    ]


# ---- setup hooks ------------------------------------------------------------

async def _seed_reminder(
    db: AsyncSession, tenant: Tenant, contact: Contact, service_ids: dict[str, uuid.UUID]
) -> None:
    """Pre-seed an upcoming appointment + a Sofia-style reminder message in
    history, so the scripted patient turn ('Confirmado!!') plays out like a
    real post-reminder confirmation instead of a cold conversation."""
    now_local = datetime.now(timezone.utc).astimezone(TZ)
    tomorrow_10h = (now_local + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)

    appt = Appointment(
        tenant_id=tenant.id,
        contact_id=contact.id,
        service_id=service_ids["limpeza"],
        scheduled_at=tomorrow_10h.astimezone(timezone.utc),
        ends_at=(tomorrow_10h + timedelta(minutes=60)).astimezone(timezone.utc),
        status=AppointmentStatus.SCHEDULED,
    )
    db.add(appt)

    reminder = Message(
        tenant_id=tenant.id,
        contact_id=contact.id,
        direction=MessageDirection.OUTBOUND,
        channel=MessageChannel.WHATSAPP,
        content=(
            "Oi! Passando pra lembrar do seu horário amanhã às 10h pra Limpeza de Pele Profunda. "
            "Consigo confirmar sua presença? 😊"
        ),
        ai_model_used=settings.DEFAULT_AI_MODEL,
        # Sent "a couple hours ago today" so it reads as recent context, not a
        # stale multi-day-old thread.
        created_at=now_local.astimezone(timezone.utc) - timedelta(hours=2),
    )
    db.add(reminder)
    await db.flush()


SCENARIOS: dict[str, Scenario] = {
    "agendamento_feliz": Scenario(
        key="agendamento_feliz",
        description=(
            "Agendamento feliz com fechamento: paciente pede serviço, aceita um horário, "
            "dá o nome, agendamento é criado."
        ),
        turns=[
            "Oi! Vocês têm horário na quinta-feira pra fazer uma limpeza de pele?",
            "pode ser às 10h então",
            "Juliana Ramos Ferreira",
            "sim, pode confirmar!",
        ],
        checks=check_agendamento_feliz,
    ),
    "quinta_que_vem": Scenario(
        key="quinta_que_vem",
        description="Data relativa ambígua ('quinta que vem') — testa a tabela de calendário do contexto.",
        turns=["Bom dia! Você tem horário pra Peeling de Diamante quinta que vem?"],
        checks=check_quinta_que_vem,
    ),
    "horario_hoje_tarde": Scenario(
        key="horario_hoje_tarde",
        description=(
            "'Agora' simulado às 16h — valida que Sofia só oferece horários futuros de hoje "
            "(correção de horário passado da Wave 1)."
        ),
        turns=["Oi, será que ainda dá pra encaixar uma limpeza de pele hoje à tarde?"],
        freeze_hour=(16, 0),
        checks=check_horario_hoje_tarde,
    ),
    "preco_nao_configurado": Scenario(
        key="preco_nao_configurado",
        description="Serviço com price=None — confirma que Sofia não inventa 'grátis' nem um valor.",
        turns=["Oi, quanto custa a drenagem linfática?"],
        checks=check_preco_nao_configurado,
    ),
    "parcelamento_nao_configurado": Scenario(
        key="parcelamento_nao_configurado",
        description="max_installments não configurado — confirma que Sofia não inventa '3x'.",
        turns=["Quanto custa o botox e dá pra parcelar em quantas vezes no cartão?"],
        checks=check_parcelamento_nao_configurado,
    ),
    "objecao_preco": Scenario(
        key="objecao_preco",
        description="Objeção de preço ('tá caro') — confirma quebra de objeção sem inventar desconto.",
        turns=[
            "Quanto custa a aplicação de botox?",
            "nossa, achei bem caro isso, tá difícil pra mim agora...",
        ],
        checks=check_objecao_preco,
    ),
    "pedido_humano": Scenario(
        key="pedido_humano",
        description="Pedido de humano — confirma request_human_handoff e que Sofia não insiste em resolver.",
        turns=["Isso aqui não tá resolvendo, quero falar com uma pessoa de verdade, por favor"],
        checks=check_pedido_humano,
    ),
    "confirmacao_pos_lembrete": Scenario(
        key="confirmacao_pos_lembrete",
        description=(
            "Confirmação de presença pós-lembrete — valida a tool confirm_appointment da Wave 1 "
            "(ver limitação conhecida se a tool ainda não existir nesta revisão)."
        ),
        turns=["Confirmado!! 👍"],
        setup=_seed_reminder,
        checks=check_confirmacao_pos_lembrete,
    ),
    "voce_e_robo": Scenario(
        key="voce_e_robo",
        description="Teste de persona — Sofia nunca revela que é uma IA.",
        turns=["Sofia, sendo bem sincera... você é um robô? isso aqui é um chatbot de IA?"],
        checks=check_voce_e_robo,
    ),
}


# ---------------------------------------------------------------------------
# DB setup / teardown
# ---------------------------------------------------------------------------

async def setup_tenant(multi_agent: bool = False) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    slug = f"e2e-sofia-{uuid.uuid4().hex[:10]}"
    ai_config = {
        "model": settings.DEFAULT_AI_MODEL,
        "temperature": 0.7,
        "max_output_tokens": 1024,
        "multimodal_enabled": False,
        "scheduling_mode": "capacity",
    }
    if multi_agent:
        # Per-tenant override — see app.services.ai.multi_agent_enabled_for.
        # Routes this test tenant's replies through
        # app/services/agents/orchestrator.py (Router + Booking/Sales/Handoff)
        # instead of the legacy single-agent path, without touching the
        # global AI_MULTI_AGENT_ENABLED default.
        ai_config["multi_agent_enabled"] = True
    async with AsyncSessionLocal() as db:
        tenant = Tenant(
            name="Espaço Beleza Viva (E2E TEST)",
            slug=slug,
            email="e2e-sofia-test@example.invalid",
            phone="1140028922",
            is_active=True,
            ai_config=ai_config,
            settings={
                "schedule": {
                    "timezone": "America/Sao_Paulo",
                    "working_days": [1, 2, 3, 4, 5],
                    "open_time": "09:00",
                    "close_time": "18:00",
                    "lunch_start": "12:00",
                    "lunch_end": "13:00",
                    "capacity": 2,
                },
                "clinic": {
                    "address": "Rua das Flores, 456 — Centro",
                    "phone": "1140028922",
                    "payment_methods": ["pix", "cartão de crédito", "dinheiro"],
                    # max_installments / evaluation_fee_mode intentionally
                    # UNSET — scenarios preco_nao_configurado / parcelamento_nao_configurado
                    # exist precisely to test the "not configured" path.
                },
                "ignore_groups": True,
            },
        )
        db.add(tenant)
        await db.flush()

        service_rows = [
            Service(tenant_id=tenant.id, name=name, duration_minutes=duration, price=price, is_active=True)
            for _key, name, price, duration in SERVICE_DEFS
        ]
        db.add_all(service_rows)
        await db.commit()
        for row in service_rows:
            await db.refresh(row)

        service_ids = {key: row.id for (key, *_rest), row in zip(SERVICE_DEFS, service_rows)}
        return tenant.id, service_ids


async def cleanup_tenant(tenant_id: Optional[uuid.UUID]) -> None:
    if tenant_id is None:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await db.commit()
    print(f"[cleanup] tenant de teste {tenant_id} removido (cascade: contatos/mensagens/agendamentos/serviços).")


async def create_contact(tenant_id: uuid.UUID) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        contact = Contact(
            tenant_id=tenant_id,
            full_name="Paciente Teste E2E",
            phone=f"5511{random.randint(900000000, 999999999)}",
            status=ContactStatus.LEAD,
            crm_stage=CrmStage.NEW_LEAD.value,
            crm_stage_source="ai",
            ai_paused=False,
        )
        db.add(contact)
        await db.commit()
        await db.refresh(contact)
        return contact.id


async def _fetch_history(
    db: AsyncSession, tenant_id: uuid.UUID, contact_id: uuid.UUID, exclude_ids: set[uuid.UUID]
) -> list[Message]:
    """Mirrors app/api/v1/routes/webhooks.py::_fetch_history — latest N
    messages excluding the current burst, oldest-first for the prompt."""
    stmt = select(Message).where(Message.tenant_id == tenant_id, Message.contact_id == contact_id)
    if exclude_ids:
        stmt = stmt.where(Message.id.not_in(exclude_ids))
    stmt = stmt.order_by(Message.created_at.desc()).limit(settings.AI_HISTORY_LIMIT)
    result = await db.execute(stmt)
    return list(reversed(result.scalars().all()))


async def run_turn(tenant_id: uuid.UUID, contact_id: uuid.UUID, patient_text: str) -> dict:
    """One inbound patient turn: persist inbound, build history exactly like
    the webhook does, call generate_reply() for real, persist outbound parts.
    Mirrors app/api/v1/routes/webhooks.py::_process_inbound_message +
    _generate_and_send, minus the WhatsApp send/typing simulation (no
    UAZAPI instance exists for this test tenant, and we don't need it)."""
    async with AsyncSessionLocal() as db:
        tenant = await db.get(Tenant, tenant_id)
        contact = await db.get(Contact, contact_id)

        inbound = Message(
            tenant_id=tenant.id,
            contact_id=contact.id,
            direction=MessageDirection.INBOUND,
            channel=MessageChannel.WHATSAPP,
            content=patient_text,
        )
        db.add(inbound)
        crm.mark_inbound(contact)
        await db.flush()

        history = await _fetch_history(db, tenant.id, contact.id, exclude_ids={inbound.id})

        reply_text, model_used = await ai_service.generate_reply(
            tenant=tenant,
            contact=contact,
            new_message=patient_text,
            history=history,
            db=db,
        )
        await db.commit()

        parts = humanizer.split_reply(reply_text)
        for part in parts:
            if part:
                db.add(
                    Message(
                        tenant_id=tenant.id,
                        contact_id=contact.id,
                        direction=MessageDirection.OUTBOUND,
                        channel=MessageChannel.WHATSAPP,
                        content=part,
                        ai_model_used=model_used,
                    )
                )
        await db.commit()
        await db.refresh(contact)

        return {
            "reply_text": reply_text,
            "reply_parts": [p for p in parts if p],
            "model_used": model_used,
            "crm_stage": contact.crm_stage,
            "crm_stage_source": contact.crm_stage_source,
            "ai_paused": contact.ai_paused,
        }


# ---------------------------------------------------------------------------
# Transcript rendering
# ---------------------------------------------------------------------------

_PRIORITY_KEYS = [
    "error", "success", "message", "crm_stage", "status", "scheduled_at_local",
    "weekday", "appointment_id", "price", "price_unset", "available_slots",
]


def _compact_repr(d: dict) -> str:
    parts = []
    for k, v in d.items():
        if isinstance(v, list) and len(v) > 6:
            v = v[:6] + ["…"]
        parts.append(f"{k}={v!r}")
    return "{" + ", ".join(parts) + "}"


def _summarize_tool_result(result) -> str:
    if not isinstance(result, dict):
        return repr(result)
    if len(result) <= 3:
        return _compact_repr(result)
    chosen = {k: result[k] for k in _PRIORITY_KEYS if k in result}
    if not chosen:
        return f"{{{len(result)} campos}}"
    omitted = len(result) - len(chosen)
    text = _compact_repr(chosen)
    if omitted > 0:
        text += f"  (+{omitted} campo(s) omitido(s))"
    return text


def _format_args(args: dict) -> str:
    if not args:
        return "—"
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


def _services_header() -> str:
    bits = []
    for _key, name, price, duration in SERVICE_DEFS:
        price_txt = f"R${price:.0f}" if price is not None else "preço não configurado"
        bits.append(f"{name} {price_txt} ({duration}min)")
    return " · ".join(bits)


def write_transcript(
    scenario: Scenario,
    tenant: Tenant,
    turn_results: list[dict],
    checks: list[str],
    effective_now_local: datetime,
    out_dir: Path,
) -> Path:
    lines: list[str] = []
    lines.append(f"# Cenário E2E — `{scenario.key}`\n")
    lines.append(f"{scenario.description}\n")
    lines.append(f"**Clínica:** {tenant.name} (slug={tenant.slug})  ")
    lines.append(f"**Serviços:** {_services_header()}  ")
    lines.append("**Horário:** Seg-Sex 09:00-18:00 (almoço 12-13h), fuso America/Sao_Paulo, capacidade 2  ")
    clinic_settings = (tenant.settings or {}).get("clinic", {})
    lines.append(f"**Avaliação/consulta:** {_evaluation_policy_info(clinic_settings)}  ")
    lines.append(f"**Parcelamento:** {_installments_info(clinic_settings)}  ")
    lines.append(f"**Modelo:** {settings.DEFAULT_AI_MODEL}  ")
    freeze_note = f" (congelado para este cenário via freeze_local_time{scenario.freeze_hour})" if scenario.freeze_hour else ""
    lines.append(f"**Agora (referência desta execução):** {effective_now_local.strftime('%A, %d/%m/%Y %H:%M')}{freeze_note}\n")
    lines.append("---\n")

    all_tool_calls: list[tuple[int, dict]] = []

    for i, result in enumerate(turn_results, start=1):
        lines.append(f"### Turno {i}")
        lines.append(f"**Paciente:** {result['patient_text']}\n")

        if result.get("error"):
            lines.append(f"**ERRO NESTE TURNO** (a execução continuou para o próximo cenário):\n```\n{result['error']}\n```\n")
            lines.append("---\n")
            continue

        stage = result.get("stage")
        lines.append(f"_(estágio de conversa detectado: `{stage}`)_\n")

        for tc in result.get("tool_calls", []):
            all_tool_calls.append((i, tc))
            lines.append(f"> 🔧 `{tc['name']}`({_format_args(tc['args'])}) → {_summarize_tool_result(tc['result'])}")
        if result.get("tool_calls"):
            lines.append("")

        lines.append("**Sofia:**")
        for part in result.get("reply_parts", []):
            lines.append(f"- {part}")
        lines.append("")

        n_parts = len(result.get("reply_parts", []))
        lines.append(
            f"_(CRM após o turno: `{result.get('crm_stage')}` / fonte `{result.get('crm_stage_source')}`"
            f"{' / ai_paused=True' if result.get('ai_paused') else ''}, {n_parts} parte(s) de mensagem)_\n"
        )
        lines.append("---\n")

    lines.append("## Resultado final")
    final = turn_results[-1] if turn_results else {}
    lines.append(f"- **Estágio CRM final:** `{final.get('crm_stage')}` (fonte: `{final.get('crm_stage_source')}`)")
    lines.append(f"- **ai_paused final:** {final.get('ai_paused')}\n")

    lines.append("### Todos os tool calls da conversa")
    if all_tool_calls:
        for turn_no, tc in all_tool_calls:
            lines.append(f"- Turno {turn_no}: `{tc['name']}`({_format_args(tc['args'])})")
    else:
        lines.append("- (nenhuma tool foi chamada nesta conversa)")
    lines.append("")

    lines.append("## Verificações automáticas (heurísticas — revisão manual recomendada)")
    lines.extend(checks or ["- (sem checagens automáticas definidas para este cenário)"])
    lines.append("")

    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).astimezone(TZ).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{scenario.key}_{ts}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def run_one_scenario(
    key: str, tenant_id: uuid.UUID, service_ids: dict[str, uuid.UUID], out_dir: Path
) -> Path:
    scenario = SCENARIOS[key]
    print(f"\n=== Cenário: {key} — {scenario.description}")
    contact_id = await create_contact(tenant_id)

    if scenario.setup:
        async with AsyncSessionLocal() as db:
            tenant = await db.get(Tenant, tenant_id)
            contact = await db.get(Contact, contact_id)
            await scenario.setup(db, tenant, contact, service_ids)
            await db.commit()

    started_at_local = datetime.now(timezone.utc).astimezone(TZ)
    freeze_ctx = (
        freeze_local_time(*scenario.freeze_hour) if scenario.freeze_hour else contextlib.nullcontext(started_at_local)
    )

    turn_results: list[dict] = []
    with freeze_ctx as effective_now_local:
        for i, patient_text in enumerate(scenario.turns, start=1):
            _TOOL_LOG.clear()
            _STAGE_LOG.clear()
            print(f"  turno {i}/{len(scenario.turns)}: chamando Gemini de verdade...")
            try:
                result = await run_turn(tenant_id, contact_id, patient_text)
                result["tool_calls"] = list(_TOOL_LOG)
                result["stage"] = _STAGE_LOG[-1] if _STAGE_LOG else None
                result["error"] = None
            except Exception:
                result = {
                    "error": traceback.format_exc(),
                    "reply_parts": [],
                    "tool_calls": list(_TOOL_LOG),
                    "stage": _STAGE_LOG[-1] if _STAGE_LOG else None,
                    "crm_stage": None,
                    "crm_stage_source": None,
                    "ai_paused": None,
                }
                print(f"  [erro] turno {i} falhou — registrado no transcript, seguindo para o próximo turno/cenário.")
            result["patient_text"] = patient_text
            turn_results.append(result)

    checks = scenario.checks(turn_results, effective_now_local) if scenario.checks else []
    out_path = write_transcript(scenario, await _get_tenant(tenant_id), turn_results, checks, effective_now_local, out_dir)
    print(f"  transcript: {out_path}")
    return out_path


async def _get_tenant(tenant_id: uuid.UUID) -> Tenant:
    async with AsyncSessionLocal() as db:
        return await db.get(Tenant, tenant_id)


def _mask_db_url(url: str) -> str:
    return re.sub(r"//([^:/@]+):([^@]*)@", "//\\1:***@", url)


def _print_scenario_list() -> None:
    print("Cenários disponíveis:")
    for key, sc in SCENARIOS.items():
        print(f"  {key:30s} ({len(sc.turns)} turno(s)) — {sc.description}")


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Harness E2E MANUAL da Sofia — chama o Gemini de verdade (custo real por chamada). "
            "Nunca rode isso em CI, cron, ou qualquer loop automatizado."
        )
    )
    p.add_argument(
        "--scenario", action="append", metavar="NOME", default=None,
        help="Roda um cenário específico (repita a flag para rodar vários). Veja os nomes com --list.",
    )
    p.add_argument("--all", action="store_true", help="Roda TODOS os cenários (pede confirmação — custo real).")
    p.add_argument("--list", action="store_true", help="Lista os cenários disponíveis e sai (sem custo/sem DB).")
    p.add_argument(
        "--yes", action="store_true",
        help="Pula a confirmação interativa do --all. Use com cautela — ainda assim gasta dinheiro real.",
    )
    p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Diretório onde os transcripts são gravados.")
    p.add_argument(
        "--multi-agent", action="store_true",
        help=(
            "Roda os cenários com a arquitetura multi-agente da Wave 3 (Router + "
            "Booking/Sales/Handoff, app/services/agents/) em vez do agente único "
            "legado — liga tenant.ai_config['multi_agent_enabled'] só no tenant "
            "de teste, não mexe na flag global AI_MULTI_AGENT_ENABLED."
        ),
    )
    return p


async def _amain(args: argparse.Namespace) -> int:
    if args.list:
        _print_scenario_list()
        return 0

    if args.all:
        keys = list(SCENARIOS.keys())
    elif args.scenario:
        keys = []
        for name in args.scenario:
            if name not in SCENARIOS:
                print(f"Cenário desconhecido: {name!r}.\n")
                _print_scenario_list()
                return 1
            keys.append(name)
    else:
        print("Nada a fazer — use --scenario NOME, --all ou --list.\n")
        _print_scenario_list()
        return 1

    total_turns = sum(len(SCENARIOS[k].turns) for k in keys)
    print(f"\nCenários selecionados: {', '.join(keys)}")
    print(f"Arquitetura: {'multi-agente (Wave 3)' if args.multi_agent else 'agente único (legado)'}")
    print(f"Banco: {_mask_db_url(settings.DATABASE_URL)}")
    print(
        f"Total de turnos = chamadas reais ao Gemini (mínimo — retries/forced-final podem somar mais): "
        f"{total_turns}\n"
    )

    if args.all and not args.yes:
        resp = input(
            f"Isso vai fazer aproximadamente {total_turns} chamadas reais à API do Gemini "
            "e pode ter custo. Confirme? [s/N] "
        ).strip().lower()
        if resp not in ("s", "sim", "y", "yes"):
            print("Cancelado — nenhuma chamada foi feita.")
            return 0

    if not settings.GEMINI_API_KEY:
        print("GEMINI_API_KEY não configurada (.env). Abortando antes de tocar no banco.")
        return 1

    out_dir = Path(args.out_dir)

    _install_capture_patches()
    tenant_id: Optional[uuid.UUID] = None
    generated: list[Path] = []
    try:
        tenant_id, service_ids = await setup_tenant(multi_agent=args.multi_agent)
        print(f"[setup] tenant de teste criado: {tenant_id}")
        for key in keys:
            try:
                path = await run_one_scenario(key, tenant_id, service_ids, out_dir)
                generated.append(path)
            except Exception:
                print(f"[erro] cenário {key!r} falhou de ponta a ponta (fora de um turno individual):")
                traceback.print_exc()
                continue
    finally:
        await cleanup_tenant(tenant_id)
        _uninstall_capture_patches()

    print(f"\nConcluído. {len(generated)}/{len(keys)} transcript(s) gerado(s):")
    for path in generated:
        print(f"  - {path}")
    return 0


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    exit_code = asyncio.run(_amain(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

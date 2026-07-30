"""
Tests for app/services/agents/orchestrator.py: pure composition helpers
(no Gemini), then the full generate_reply() flow with SequencedFakeClient
covering the modes described in its module docstring — single, composite
(join), escalation (replace-not-append), and handoff-direct.

Includes the single most important test in the multi-agent package: proving
that a specialist's rogue/hallucinated call to a tool it wasn't given (here,
Sales "calling" create_appointment) is rejected before app.services.ai_tools
.execute_tool ever runs, and that no Appointment is created — the concrete,
testable form of "Sales can't book."
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.agents import orchestrator
from tests.support.fake_gemini import SequencedFakeClient, fake_function_call, fake_text


def _tenant(multi_agent=True):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Clínica Teste",
        settings={},
        ai_config={"multi_agent_enabled": multi_agent},
    )


def _contact(crm_stage="new_lead", tenant_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        full_name="Paciente Teste",
        status="lead",
        crm_stage=crm_stage,
        whatsapp_name=None,
        email=None,
        phone=None,
        date_of_birth=None,
    )


class _FakeDB:
    """Minimal stand-in for AsyncSession: ai_stages.analyze() runs a real
    SQLAlchemy `select(Appointment)...` and calls `db.execute(...)`, then
    `.scalars().all()` — this fake always returns zero rows (no appointments),
    which is enough for these orchestrator-flow tests (they don't exercise
    stage-specific behavior, just which agent(s) run and how texts compose).
    """

    async def execute(self, *args, **kwargs):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))


class TestPureCompositionHelpers:
    def test_join_composite_texts_both_nonempty(self):
        joined = orchestrator.join_composite_texts("Custa R$180.", "Tenho quinta às 10h.")
        assert joined == "Custa R$180.[[BREAK]]Tenho quinta às 10h."

    def test_join_composite_texts_one_empty(self):
        assert orchestrator.join_composite_texts("Custa R$180.", "") == "Custa R$180."
        assert orchestrator.join_composite_texts("", "Tenho quinta às 10h.") == "Tenho quinta às 10h."

    def test_join_composite_texts_both_empty(self):
        assert orchestrator.join_composite_texts("", "") == ""

    def test_coordination_note_present_when_previous_text_given(self):
        note = orchestrator.coordination_note_for("Custa R$180.")
        assert note is not None
        assert "Custa R$180." in note
        assert "NOTA INTERNA" in note

    def test_coordination_note_absent_when_previous_text_empty(self):
        assert orchestrator.coordination_note_for("") is None

    def test_compose_system_prompt_includes_all_sections(self):
        prompt = orchestrator.compose_system_prompt(
            "OVERLAY_TEXT", "IDENTITY_TEXT", "STAGE_TEXT", "CONTEXT_TEXT", "NOTE_TEXT"
        )
        for expected in ("OVERLAY_TEXT", "IDENTITY_TEXT", "STAGE_TEXT", "CONTEXT_TEXT", "NOTE_TEXT"):
            assert expected in prompt

    def test_compose_system_prompt_omits_note_when_none(self):
        prompt = orchestrator.compose_system_prompt("O", "I", "S", "C", None)
        assert "NOTA INTERNA" not in prompt


def _patched_client(monkeypatch, client):
    """Patch _get_client at the point orchestrator.py looks it up."""
    monkeypatch.setattr(orchestrator, "_get_client", lambda: client)


class TestGenerateReplyModes:
    async def test_single_agent_mode_returns_specialist_text_directly(self, monkeypatch):
        client = SequencedFakeClient([
            fake_function_call("classify", {"agents": ["sales"]}),  # router
            fake_text("Fazemos limpeza de pele por R$180."),  # sales specialist
        ])
        _patched_client(monkeypatch, client)

        text, model = await orchestrator.generate_reply(
            tenant=_tenant(), contact=_contact(), new_message="quanto custa a limpeza?",
            history=[], db=_FakeDB(),
        )
        assert text == "Fazemos limpeza de pele por R$180."
        assert len(client.models.calls) == 2

    async def test_composite_mode_joins_both_specialists(self, monkeypatch):
        client = SequencedFakeClient([
            fake_function_call("classify", {"agents": ["sales", "booking"]}),  # router
            fake_text("A limpeza de pele custa R$180."),  # sales
            fake_text("Tenho quinta às 10h ou sexta às 15h."),  # booking
        ])
        _patched_client(monkeypatch, client)

        text, model = await orchestrator.generate_reply(
            tenant=_tenant(), contact=_contact(),
            new_message="quanto custa a limpeza e tem horário essa semana?",
            history=[], db=_FakeDB(),
        )
        assert text == "A limpeza de pele custa R$180.[[BREAK]]Tenho quinta às 10h ou sexta às 15h."
        assert len(client.models.calls) == 3  # router + 2 specialists, no 3rd hop possible

    async def test_upset_patient_is_handled_by_sales_not_handed_off(self, monkeypatch):
        # A patient asking for a human / complaining routes to Sales, which
        # resolves the turn itself — there is no handoff path to escalate to.
        client = SequencedFakeClient([
            fake_function_call("classify", {"agents": ["sales"]}),  # router
            fake_text("Poxa, sinto muito que ficou assim! Me conta o que aconteceu que eu resolvo com você 💛"),
        ])
        _patched_client(monkeypatch, client)

        text, model = await orchestrator.generate_reply(
            tenant=_tenant(), contact=_contact(), new_message="quero falar com uma pessoa de verdade, isso é péssimo",
            history=[], db=_FakeDB(),
        )
        assert "resolvo com você" in text
        assert len(client.models.calls) == 2  # router + sales, no escalation hop


class TestSalesCannotBookEvenIfItTries:
    async def test_rogue_create_appointment_call_from_sales_is_rejected_and_no_appointment_created(self, monkeypatch):
        """
        The concrete, testable form of "o Agente de Vendas não consegue
        marcar consultas": script the Sales specialist "calling"
        create_appointment (structurally impossible via the real Gemini API
        since that tool is never declared to Sales — see
        tests/test_agents_tool_partition.py for the structural proof — this
        test proves the RUNTIME gate holds too, as defense in depth, and
        that no DB write happens).
        """
        client = SequencedFakeClient([
            fake_function_call("classify", {"agents": ["sales"]}),  # router
            fake_function_call("create_appointment", {"scheduled_at": "2026-01-01T10:00:00"}),  # rogue call
            fake_text("Desculpe, não consigo agendar por aqui — mas posso te ajudar com outra coisa!"),
        ])
        _patched_client(monkeypatch, client)

        with patch("app.services.agents.base.execute_tool", new=AsyncMock()) as mock_execute:
            text, model = await orchestrator.generate_reply(
                tenant=_tenant(), contact=_contact(), new_message="pode marcar pra mim?",
                history=[], db=_FakeDB(),
            )
            mock_execute.assert_not_called()

        assert "não consigo agendar" in text

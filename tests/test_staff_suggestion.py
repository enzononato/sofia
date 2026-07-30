"""
Unit tests for the staff "Sugerir resposta" copilot
(app/services/ai.py::generate_staff_suggestion) — no DB/Postgres, no real
Gemini. Proves the two safety-critical properties of a DRAFT:
  1. it can NEVER call a write tool (read-only tool subset + the loop's
     allowlist gate), so drafting a suggestion has zero side effects;
  2. the internal [[BREAK]] split marker is flattened for the human to read.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import ai as ai_service
from app.services.ai import _SUGGESTION_READONLY_TOOLS
from tests.support.fake_gemini import SequencedFakeClient, fake_function_call, fake_text


def _tenant():
    return SimpleNamespace(id=uuid.uuid4(), name="Clínica Teste", settings={}, ai_config={})


def _contact(crm_stage="new_lead"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        full_name="Paciente Teste",
        status="lead",
        crm_stage=crm_stage,
        whatsapp_name=None,
        email=None,
        phone=None,
        date_of_birth=None,
    )


class _FakeDB:
    """ai_stages.analyze runs a real select(Appointment) and calls db.execute →
    .scalars().all(); zero rows is enough for these tests."""

    async def execute(self, *args, **kwargs):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))


class TestReadOnlyToolset:
    def test_suggestion_toolset_excludes_every_write_tool(self):
        write_tools = {
            "create_appointment",
            "reschedule_appointment",
            "cancel_appointment",
            "confirm_appointment",
            "update_contact_info",
            "set_crm_stage",
            "request_human_handoff",
        }
        assert _SUGGESTION_READONLY_TOOLS & write_tools == set()


class TestGenerateStaffSuggestion:
    async def test_returns_plain_text_and_flattens_break_marker(self, monkeypatch):
        client = SequencedFakeClient([fake_text("Oi Maria![[BREAK]]Consigo quinta às 14h.")])
        monkeypatch.setattr(ai_service, "_get_client", lambda: client)

        text = await ai_service.generate_staff_suggestion(
            tenant=_tenant(), contact=_contact(), history=[], db=_FakeDB(),
        )
        assert "[[BREAK]]" not in text
        assert text == "Oi Maria!\n\nConsigo quinta às 14h."
        # One Gemini call: no tools were invoked for a plain-text draft.
        assert len(client.models.calls) == 1

    async def test_rogue_write_tool_call_is_blocked_and_never_executed(self, monkeypatch):
        # If the model tries a write tool (structurally impossible via the real
        # API since it's never declared), the loop's allowlist gate rejects it
        # BEFORE execute_tool — proving a draft can't book/change anything.
        client = SequencedFakeClient([
            fake_function_call("create_appointment", {"scheduled_at": "2026-01-01T10:00:00"}),
            fake_text("Consigo te encaixar quinta às 14h, quer que eu deixe reservado?"),
        ])
        monkeypatch.setattr(ai_service, "_get_client", lambda: client)

        with patch("app.services.agents.base.execute_tool", new=AsyncMock()) as mock_execute:
            text = await ai_service.generate_staff_suggestion(
                tenant=_tenant(), contact=_contact(), history=[], db=_FakeDB(),
            )
            mock_execute.assert_not_called()

        assert "quinta" in text
        assert len(client.models.calls) == 2  # rejected tool turn + final text

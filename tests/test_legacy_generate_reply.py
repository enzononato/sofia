"""
Characterization tests for the LEGACY single-agent reply path
(app/services/ai.py::_legacy_generate_reply) — the production-default path
(the multi-agent path costs 2-3 Gemini calls per turn and ships off).

Its hand-rolled tool-calling loop was replaced by a call to the shared
app/services/agents/base.py::run_specialist_loop, passing
max_iterations=MAX_TOOL_ITERATIONS (8) — distinct from the shared loop's own
default, SPECIALIST_MAX_TOOL_ITERATIONS (4), used by the specialists and the
staff copilot. Nothing else in either test suite executes this function
(integration tests monkeypatch generate_reply wholesale; test_agents_base.py
exercises the shared loop directly, always with the default max_iterations),
so "the legacy path behaves identically after the refactor" rested entirely
on code reading. These tests are pure/in-memory — no DB, no network — and
follow the harness established in tests/test_staff_suggestion.py.

The third test is the one that matters most: it pins the 8-iteration budget
so a future edit to the shared loop's default can't silently truncate
multi-tool bookings for every clinic in production without a test failing.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import ai as ai_service
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


class TestLegacyGenerateReplyPlainText:
    async def test_returns_text_and_model_with_a_single_gemini_call(self, monkeypatch):
        client = SequencedFakeClient([fake_text("Oi! Claro, posso te ajudar com isso.")])
        monkeypatch.setattr(ai_service, "_get_client", lambda: client)

        text, model = await ai_service._legacy_generate_reply(
            tenant=_tenant(),
            contact=_contact(),
            new_message="Oi, vocês fazem limpeza de pele?",
            history=[],
            db=_FakeDB(),
        )

        assert text == "Oi! Claro, posso te ajudar com isso."
        assert model == settings.DEFAULT_AI_MODEL
        # A plain-text reply needs no tool calls: exactly one Gemini call.
        assert len(client.models.calls) == 1


class TestLegacyGenerateReplyToolCall:
    async def test_tool_call_reaches_execute_tool_via_the_shared_loop(self, monkeypatch):
        # Scripted: the model calls a real, legitimate legacy tool, then
        # answers in text once it has the tool's result. Patched where the
        # shared loop looks it up (app.services.agents.base.execute_tool) —
        # NOT app.services.ai_tools.execute_tool nor app.services.ai — since
        # ai.py no longer imports execute_tool at all, only agents/base.py
        # does. This proves the new allowed_tool_names gate does not block a
        # legitimate legacy tool from actually reaching the executor.
        client = SequencedFakeClient([
            fake_function_call("list_services", {}),
            fake_text("Temos limpeza de pele, botox e peeling disponíveis."),
        ])
        monkeypatch.setattr(ai_service, "_get_client", lambda: client)

        with patch(
            "app.services.agents.base.execute_tool",
            new=AsyncMock(return_value={"services": []}),
        ) as mock_execute:
            text, model = await ai_service._legacy_generate_reply(
                tenant=_tenant(),
                contact=_contact(),
                new_message="Quais serviços vocês têm?",
                history=[],
                db=_FakeDB(),
            )
            mock_execute.assert_called_once()
            assert mock_execute.call_args.kwargs["name"] == "list_services"

        assert text == "Temos limpeza de pele, botox e peeling disponíveis."
        assert len(client.models.calls) == 2  # tool-call turn + final text turn


class TestLegacyGenerateReplyIterationBudget:
    async def test_runs_eight_iterations_before_forced_final_not_four(self, monkeypatch):
        # This is the test that matters most: _legacy_generate_reply passes
        # max_iterations=MAX_TOOL_ITERATIONS (8) to run_specialist_loop,
        # explicitly overriding the shared loop's own default,
        # SPECIALIST_MAX_TOOL_ITERATIONS (4). Script exactly 8 consecutive
        # tool-call turns (the loop's whole budget) followed by ONE more
        # scripted response for the forced-final completion (tools disabled)
        # that the loop makes after exhausting its budget. If the shared
        # loop's default were ever restored to 4 on this path, the model
        # would only get to call the tool 4 times before the forced-final
        # completion consumed the 5th (still a bare function-call, no text)
        # scripted response, so this test must fail — see the mutation proof
        # in the fix report.
        responses = [fake_function_call("list_services", {}) for _ in range(8)]
        responses.append(fake_text("Desculpa a demora, consegui reunir as informações."))
        client = SequencedFakeClient(responses)
        monkeypatch.setattr(ai_service, "_get_client", lambda: client)

        with patch(
            "app.services.agents.base.execute_tool",
            new=AsyncMock(return_value={"services": []}),
        ) as mock_execute:
            text, model = await ai_service._legacy_generate_reply(
                tenant=_tenant(),
                contact=_contact(),
                new_message="Preciso de uma ajuda complicada",
                history=[],
                db=_FakeDB(),
            )

        # Distinguishes 8 from 4 unambiguously: under a 4-iteration budget,
        # execute_tool would be called only 4 times and only 5 Gemini calls
        # total would be made (see this test's docstring above).
        assert mock_execute.call_count == 8
        assert len(client.models.calls) == 9  # 8 tool-call iterations + 1 forced-final completion
        assert text == "Desculpa a demora, consegui reunir as informações."

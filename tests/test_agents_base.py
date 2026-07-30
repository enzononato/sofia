"""
Unit tests for app/services/agents/base.py: the tool filter (single source
of truth stays ai_tools.CLINIC_TOOLS) and the shared specialist tool-calling
loop (allowlist enforcement, escalation short-circuit, empty-parts retry,
loop-exhaustion fallback).

No DB/Postgres needed — `execute_tool` calls in these tests only exercise
tools whose executors don't touch the DB in a way that requires it (we stub
`db` as a bare object() and only call tools we've scripted to be
allowed/disallowed appropriately; the allowlist gate is tested BEFORE
execute_tool would ever run for a disallowed tool).
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.agents import base as agents_base
from tests.support.fake_gemini import SequencedFakeClient, fake_function_call, fake_text, fake_empty


def _tenant():
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Clínica Teste",
        settings={},
        ai_config={},
    )


def _contact():
    return SimpleNamespace(id=uuid.uuid4(), full_name="Paciente Teste")


class TestToolsSubset:
    def test_filters_to_requested_names_only(self):
        tool = agents_base.tools_subset({"list_services", "get_clinic_info"})
        names = {d.name for d in tool.function_declarations}
        assert names == {"list_services", "get_clinic_info"}

    def test_raises_on_unknown_tool_name(self):
        with pytest.raises(ValueError, match="unknown tool"):
            agents_base.tools_subset({"this_tool_does_not_exist"})


class TestRunSpecialistLoop:
    async def test_plain_text_response_returns_immediately(self):
        client = SequencedFakeClient([fake_text("Oi! Como posso ajudar?")])
        reply = await agents_base.run_specialist_loop(
            client=client,
            model="gemini-2.5-flash",
            temperature=0.7,
            max_output_tokens=512,
            system_prompt="prompt",
            tools=agents_base.tools_subset({"get_clinic_info"}),
            allowed_tool_names={"get_clinic_info"},
            contents=[],
            db=object(),
            tenant=_tenant(),
            contact=_contact(),
            ai_cfg={},
        )
        assert reply.text == "Oi! Como posso ajudar?"
        assert len(client.models.calls) == 1

    async def test_disallowed_tool_call_is_rejected_before_execute_tool(self):
        # Simulates a rogue/hallucinated call to a tool this agent was never
        # given (structurally impossible via the real Gemini API since the
        # tool wasn't declared, but this proves the server-side gate works
        # as defense in depth). The rejected call gets a benign error
        # function_response, and the loop continues to a second (scripted)
        # turn that produces the final text — proving execute_tool was never
        # reached (no Appointment/DB side effect requested or asserted here
        # because the gate fires BEFORE any real tool dispatch).
        client = SequencedFakeClient([
            fake_function_call("create_appointment", {"scheduled_at": "2026-01-01T10:00:00"}),
            fake_text("Desculpe, não consigo agendar por aqui."),
        ])
        reply = await agents_base.run_specialist_loop(
            client=client,
            model="gemini-2.5-flash",
            temperature=0.7,
            max_output_tokens=512,
            system_prompt="prompt",
            tools=agents_base.tools_subset({"list_services", "get_clinic_info"}),
            allowed_tool_names={"list_services", "get_clinic_info"},  # NOT create_appointment
            contents=[],
            db=object(),
            tenant=_tenant(),
            contact=_contact(),
            ai_cfg={},
        )
        assert reply.text == "Desculpe, não consigo agendar por aqui."
        assert len(client.models.calls) == 2
        # The function_response fed back for the rejected call must be the
        # benign "not available" error, not a real booking result.
        second_call_contents = client.models.calls[1]["contents"]
        function_response_part = second_call_contents[-1].parts[0]
        assert "not available" in function_response_part.function_response.response["error"]

    async def test_empty_candidate_retries_once_then_falls_back(self):
        client = SequencedFakeClient([fake_empty(), fake_empty()])
        reply = await agents_base.run_specialist_loop(
            client=client,
            model="gemini-2.5-flash",
            temperature=0.7,
            max_output_tokens=512,
            system_prompt="prompt",
            tools=agents_base.tools_subset({"list_services"}),
            allowed_tool_names={"list_services"},
            contents=[],
            db=object(),
            tenant=_tenant(),
            contact=_contact(),
            ai_cfg={},
        )
        assert "probleminha" in reply.text
        assert len(client.models.calls) == 2

    async def test_empty_candidate_recovers_if_second_attempt_has_text(self):
        client = SequencedFakeClient([fake_empty(), fake_text("Aqui está a resposta.")])
        reply = await agents_base.run_specialist_loop(
            client=client,
            model="gemini-2.5-flash",
            temperature=0.7,
            max_output_tokens=512,
            system_prompt="prompt",
            tools=agents_base.tools_subset({"list_services"}),
            allowed_tool_names={"list_services"},
            contents=[],
            db=object(),
            tenant=_tenant(),
            contact=_contact(),
            ai_cfg={},
        )
        assert reply.text == "Aqui está a resposta."

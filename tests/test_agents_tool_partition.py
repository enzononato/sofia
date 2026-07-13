"""
Structural proof of tool exclusivity between specialists — no Gemini call,
no DB. This is the primary machine-checkable evidence for the requirement
"o Agente de Vendas não consegue marcar consultas": Sales's declared tool
set structurally cannot include a booking-write tool, so even a
hallucinating model has no function to call.

See tests/test_agents_base.py::TestRunSpecialistLoop for the runtime
defense-in-depth proof (the allowed_tool_names gate rejecting a rogue call
even if one somehow arrived).
"""

from app.services.agents import booking, handoff, sales
from app.services.agents.base import ESCALATE_TOOL_NAME

WRITE_TOOLS = {
    "create_appointment",
    "reschedule_appointment",
    "cancel_appointment",
    "confirm_appointment",
    "update_contact_info",
    "set_crm_stage",
    "request_human_handoff",
}

EXPECTED_WRITE_OWNERS = {
    "booking": {
        "create_appointment",
        "reschedule_appointment",
        "cancel_appointment",
        "confirm_appointment",
        "update_contact_info",
    },
    "sales": {"set_crm_stage"},
    "handoff": {"request_human_handoff"},
}


def _declared_names(tool) -> set[str]:
    return {d.name for d in tool.function_declarations}


class TestWriteToolExclusivity:
    def test_each_agent_declares_exactly_its_expected_write_tools(self):
        declared = {
            "booking": _declared_names(booking.TOOLS),
            "sales": _declared_names(sales.TOOLS),
            "handoff": _declared_names(handoff.TOOLS),
        }
        for agent, expected in EXPECTED_WRITE_OWNERS.items():
            assert declared[agent] & WRITE_TOOLS == expected, (
                f"{agent} declares unexpected write tools: "
                f"{(declared[agent] & WRITE_TOOLS) - expected}, "
                f"missing: {expected - (declared[agent] & WRITE_TOOLS)}"
            )

    def test_no_write_tool_is_declared_by_more_than_one_agent(self):
        declared = {
            "booking": _declared_names(booking.TOOLS),
            "sales": _declared_names(sales.TOOLS),
            "handoff": _declared_names(handoff.TOOLS),
        }
        all_write_occurrences = [
            name for names in declared.values() for name in names if name in WRITE_TOOLS
        ]
        assert len(all_write_occurrences) == len(set(all_write_occurrences))

    def test_sales_cannot_book_write_tools_absent(self):
        # The literal requirement from the request: prove Sales structurally
        # cannot call any appointment-writing tool.
        names = _declared_names(sales.TOOLS)
        booking_write_tools = {
            "create_appointment", "reschedule_appointment", "cancel_appointment", "confirm_appointment",
        }
        assert names & booking_write_tools == set()

    def test_booking_cannot_set_crm_stage_or_handoff(self):
        names = _declared_names(booking.TOOLS)
        assert "set_crm_stage" not in names
        assert "request_human_handoff" not in names

    def test_only_handoff_holds_request_human_handoff(self):
        assert "request_human_handoff" in _declared_names(handoff.TOOLS)
        assert "request_human_handoff" not in _declared_names(booking.TOOLS)
        assert "request_human_handoff" not in _declared_names(sales.TOOLS)


class TestEscalationToolWiring:
    def test_booking_and_sales_have_escalate_but_handoff_does_not(self):
        assert ESCALATE_TOOL_NAME in _declared_names(booking.TOOLS)
        assert ESCALATE_TOOL_NAME in _declared_names(sales.TOOLS)
        assert ESCALATE_TOOL_NAME not in _declared_names(handoff.TOOLS)

    def test_tool_names_constants_match_declared_tools_minus_escalate(self):
        # Guards against TOOL_NAMES (used for allowed_tool_names) drifting
        # from what was actually declared to Gemini for that agent.
        assert booking.TOOL_NAMES == _declared_names(booking.TOOLS) - {ESCALATE_TOOL_NAME}
        assert sales.TOOL_NAMES == _declared_names(sales.TOOLS) - {ESCALATE_TOOL_NAME}
        assert handoff.TOOL_NAMES == _declared_names(handoff.TOOLS)

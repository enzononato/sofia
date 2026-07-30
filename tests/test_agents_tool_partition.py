"""
Structural proof of tool exclusivity between specialists — no Gemini call,
no DB. This is the primary machine-checkable evidence for the requirement
"o Agente de Vendas não consegue marcar consultas": Sales's declared tool
set structurally cannot include a booking-write tool, so even a
hallucinating model has no function to call.

There are only two specialists (Booking / Sales) — Sofia never hands off to a
human, so there is no Handoff agent and no escalation signal tool.

See tests/test_agents_base.py::TestRunSpecialistLoop for the runtime
defense-in-depth proof (the allowed_tool_names gate rejecting a rogue call
even if one somehow arrived).
"""

from app.services.agents import booking, sales

# Tools whose owner must be EXCLUSIVE. `confirm_appointment` is deliberately not
# here: it only flips an existing booking's status (SCHEDULED -> CONFIRMED), it
# never creates, moves or cancels a slot, and Sales — the Router's default route
# — must be able to register a patient answering "sim, confirmo" to a reminder.
WRITE_TOOLS = {
    "create_appointment",
    "reschedule_appointment",
    "cancel_appointment",
    "update_contact_info",
    "set_crm_stage",
}

EXPECTED_WRITE_OWNERS = {
    "booking": {
        "create_appointment",
        "reschedule_appointment",
        "cancel_appointment",
        "update_contact_info",
    },
    "sales": {"set_crm_stage"},
}


def _declared_names(tool) -> set[str]:
    return {d.name for d in tool.function_declarations}


class TestWriteToolExclusivity:
    def test_each_agent_declares_exactly_its_expected_write_tools(self):
        declared = {
            "booking": _declared_names(booking.TOOLS),
            "sales": _declared_names(sales.TOOLS),
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
        }
        all_write_occurrences = [
            name for names in declared.values() for name in names if name in WRITE_TOOLS
        ]
        assert len(all_write_occurrences) == len(set(all_write_occurrences))

    def test_sales_cannot_book_write_tools_absent(self):
        # The literal requirement from the request: prove Sales structurally
        # cannot call any tool that WRITES to the schedule. Note that
        # `confirm_appointment` is deliberately NOT in this set — Sales is the
        # Router's default route, and a patient answering "sim, confirmo" to a
        # reminder must be registrable there (it updates an existing booking's
        # status, it never creates or moves a slot).
        names = _declared_names(sales.TOOLS)
        booking_write_tools = {
            "create_appointment", "reschedule_appointment", "cancel_appointment",
        }
        assert names & booking_write_tools == set()

    def test_booking_cannot_set_crm_stage(self):
        names = _declared_names(booking.TOOLS)
        assert "set_crm_stage" not in names

    def test_read_only_tools_may_be_shared_by_both_agents(self):
        # Read tools are intentionally NOT exclusive: each agent needs enough
        # context to answer without stalling or inventing.
        for shared in ("list_services", "list_professionals", "get_clinic_info",
                       "check_availability", "get_upcoming_appointments"):
            assert shared in _declared_names(sales.TOOLS) or shared in _declared_names(booking.TOOLS)
        assert "get_clinic_info" in _declared_names(booking.TOOLS)
        assert "check_availability" in _declared_names(sales.TOOLS)


class TestNoHandoffTool:
    def test_no_agent_declares_request_human_handoff(self):
        # Conversational handoff was removed — no specialist may hold the tool.
        assert "request_human_handoff" not in _declared_names(booking.TOOLS)
        assert "request_human_handoff" not in _declared_names(sales.TOOLS)

    def test_no_agent_declares_an_escalation_tool(self):
        assert "escalate_to_human" not in _declared_names(booking.TOOLS)
        assert "escalate_to_human" not in _declared_names(sales.TOOLS)

    def test_tool_names_constants_match_declared_tools(self):
        # Guards against TOOL_NAMES (used for allowed_tool_names) drifting
        # from what was actually declared to Gemini for that agent. With no
        # escalation tool, the declared set now equals TOOL_NAMES exactly.
        assert booking.TOOL_NAMES == _declared_names(booking.TOOLS)
        assert sales.TOOL_NAMES == _declared_names(sales.TOOLS)

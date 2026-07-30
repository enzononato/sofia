"""
Machine-checkable invariants for Sofia's prompt text.

A prompt audit found rules that cancelled each other out with IDENTICAL strings
(a phrase banned in one section and recommended in another), instructions to use
tools the agent of that turn doesn't hold, and leftovers from the removed human
handoff. Those are exactly the kind of regression a human reviewer misses in a
20k-character prompt, so they are pinned here.

These tests assert on STRUCTURE and CONTRADICTIONS, never on wording quality —
rewording a rule must not break them, but reintroducing a contradiction must.
"""

import re

from app.services import prompts
from app.services.agents import booking, sales
from app.services.agents.base import SHARED_BASE_PROMPT
from app.services.ai import DEFAULT_SYSTEM_PROMPT

ALL_PROMPTS = {
    "core": prompts.SOFIA_CORE_PROMPT,
    "sales_playbook": prompts.SALES_PLAYBOOK,
    "booking_playbook": prompts.BOOKING_PLAYBOOK,
    "legacy_composed": DEFAULT_SYSTEM_PROMPT,
    "sales_overlay": sales.OVERLAY,
    "booking_overlay": booking.OVERLAY,
}


class TestSingleSourceOfTruth:
    def test_legacy_prompt_is_composed_from_the_shared_pieces(self):
        # The two paths must not drift again: the legacy single-agent prompt is
        # literally CORE + both playbooks, not a parallel copy.
        assert prompts.SOFIA_CORE_PROMPT in DEFAULT_SYSTEM_PROMPT
        assert prompts.SALES_PLAYBOOK in DEFAULT_SYSTEM_PROMPT
        assert prompts.BOOKING_PLAYBOOK in DEFAULT_SYSTEM_PROMPT

    def test_multi_agent_base_is_exactly_the_core(self):
        assert SHARED_BASE_PROMPT == prompts.SOFIA_CORE_PROMPT

    def test_each_specialist_carries_its_playbook(self):
        assert prompts.SALES_PLAYBOOK in sales.OVERLAY
        assert prompts.BOOKING_PLAYBOOK in booking.OVERLAY


class TestNoHandoffLeftovers:
    """Sofia never transfers to a human — no prompt may imply otherwise."""

    def test_no_prompt_tells_her_to_forward_the_conversation(self):
        for name, text in ALL_PROMPTS.items():
            low = text.lower()
            assert "encaminhe" not in low, f"{name} still tells Sofia to forward"
            assert "passar pra quem" not in low, f"{name} still delegates to someone else"

    def test_a_false_handoff_claim_is_only_ever_forbidden(self):
        # "o agendamento já está encaminhado" was an INSTRUCTION to assert
        # something false (nothing was booked, there is no queue). The phrase may
        # now only survive inside a prohibition.
        for name, text in ALL_PROMPTS.items():
            for line in _lines_containing(text, "está encaminhado"):
                assert _is_prohibition(line), (
                    f"{name} tells Sofia to claim a booking is under way: {line.strip()[:120]}"
                )

    def test_no_prompt_promises_a_callback_she_cannot_make(self):
        # She has no queue, no ticket and no way to come back later: promising a
        # return leaves the patient waiting forever. The strings may only appear
        # inside an explicit prohibition.
        for name, text in ALL_PROMPTS.items():
            for line in text.split("\n"):
                low = line.lower()
                if "te retorno" in low or "te falo" in low or "já te aviso" in low:
                    assert ("nunca" in low or "não " in low or "nao " in low), (
                        f"{name} appears to RECOMMEND promising a callback: {line.strip()[:120]}"
                    )


class TestNoSelfContradiction:
    def test_a_banned_filler_is_never_also_recommended(self):
        # The audit found "consigo sim" banned as a robotic tic and recommended
        # as a natural reaction five lines later, and "fico à disposição" banned
        # while used as the preferred closing example.
        banned = _banned_filler_phrases(prompts.SOFIA_CORE_PROMPT)
        assert banned, "could not locate the banned-filler list; update this test"
        for name, text in ALL_PROMPTS.items():
            for phrase in banned:
                occurrences = _lines_containing(text, phrase)
                for line in occurrences:
                    assert _is_prohibition(line), (
                        f"{name} uses banned filler {phrase!r} as an example: {line.strip()[:120]}"
                    )

    def test_prompt_body_never_uses_the_em_dash_it_forbids(self):
        # The system prompt is the strongest style example the model has: banning
        # em-dashes while using them 100+ times trains the opposite behaviour.
        for name, text in ALL_PROMPTS.items():
            assert "—" not in text, f"{name} contains an em-dash the prompt forbids"


class TestToolsMatchInstructions:
    """No prompt may order an agent to use a tool it wasn't given."""

    TOOL_NAMES = [
        "list_services",
        "check_availability",
        "create_appointment",
        "reschedule_appointment",
        "cancel_appointment",
        "confirm_appointment",
        "get_upcoming_appointments",
        "get_clinic_info",
        "update_contact_info",
        "list_professionals",
        "set_crm_stage",
    ]

    def test_sales_overlay_only_names_tools_sales_has(self):
        self._assert_named_tools_are_available(sales.OVERLAY, sales.TOOL_NAMES, "sales")

    def test_booking_overlay_only_names_tools_booking_has(self):
        self._assert_named_tools_are_available(booking.OVERLAY, booking.TOOL_NAMES, "booking")

    def test_core_prompt_only_names_tools_every_agent_has(self):
        common = sales.TOOL_NAMES & booking.TOOL_NAMES
        self._assert_named_tools_are_available(prompts.SOFIA_CORE_PROMPT, common, "core")

    def _assert_named_tools_are_available(self, text: str, available: set[str], label: str):
        named = {t for t in self.TOOL_NAMES if re.search(rf"\b{t}\b", text)}
        missing = named - set(available)
        assert not missing, (
            f"{label} prompt names tool(s) it cannot call: {sorted(missing)}. "
            "Either grant the tool or stop naming it (ground the rule in the context block)."
        )


class TestSalesIsASafeDefaultRoute:
    """Sales is the Router's fallback, so it must cover the fallback duties."""

    def test_sales_can_check_availability_and_confirm_attendance(self):
        # A patient replying "sim, confirmo" to a reminder can land on the
        # default route; without confirm_appointment that confirmation was
        # silently lost. Reading the schedule is likewise table stakes.
        assert "check_availability" in sales.TOOL_NAMES
        assert "confirm_appointment" in sales.TOOL_NAMES
        assert "get_upcoming_appointments" in sales.TOOL_NAMES

    def test_sales_still_cannot_write_to_the_schedule(self):
        # Read-only additions must not erode the write partition.
        for write_tool in ("create_appointment", "reschedule_appointment", "cancel_appointment"):
            assert write_tool not in sales.TOOL_NAMES

    def test_booking_can_answer_factual_clinic_questions(self):
        assert "get_clinic_info" in booking.TOOL_NAMES


class TestPersonaLock:
    def test_virtual_self_descriptions_are_banned(self):
        # "secretária virtual" was the most likely pt-BR slip and was missing
        # from the banned list — it appeared in both manual transcripts.
        low = prompts.SOFIA_CORE_PROMPT.lower()
        assert "virtual" in low
        assert "secretária virtual" in low

    def test_tool_output_must_not_be_repeated_to_the_patient(self):
        low = prompts.SOFIA_CORE_PROMPT.lower()
        assert "nunca copie" in low or "não copie" in low

    def test_health_conditions_rule_exists(self):
        low = prompts.SOFIA_CORE_PROMPT.lower()
        assert "gravidez" in low and "amamenta" in low


# ── helpers ──────────────────────────────────────────────────────────────────

def _banned_filler_phrases(core: str) -> list[str]:
    """Pull the quoted phrases out of the 'evite frases feitas' rule."""
    for line in core.split("\n"):
        if "frases feitas" in line.lower():
            return re.findall(r'"([^"]+)"', line)
    return []


def _lines_containing(text: str, phrase: str) -> list[str]:
    return [ln for ln in text.split("\n") if phrase.lower() in ln.lower()]


def _is_prohibition(line: str) -> bool:
    low = line.lower()
    return any(w in low for w in ("evite", "nunca", "não ", "nao ", "proibido", "fuja"))

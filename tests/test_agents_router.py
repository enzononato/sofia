"""
Tests for app/services/agents/router.py: parse_decision is pure (no Gemini
needed), classify() is tested end-to-end with SequencedFakeClient.
"""

import uuid
from types import SimpleNamespace

from app.services.agents import router
from tests.support.fake_gemini import SequencedFakeClient, fake_function_call, fake_text


def _tenant():
    return SimpleNamespace(id=uuid.uuid4(), name="Clínica Teste", settings={}, ai_config={})


def _contact(crm_stage="new_lead"):
    return SimpleNamespace(id=uuid.uuid4(), full_name="Paciente", crm_stage=crm_stage)


class TestParseDecision:
    def test_single_agent(self):
        resp = fake_function_call("classify", {"agents": ["booking"]})
        decision = router.parse_decision(resp)
        assert decision == router.RouterDecision(agents=["booking"])

    def test_composite_two_agents_preserves_order(self):
        resp = fake_function_call("classify", {"agents": ["sales", "booking"]})
        decision = router.parse_decision(resp)
        assert decision.agents == ["sales", "booking"]

    def test_handoff_never_combined_even_if_model_tries(self):
        resp = fake_function_call("classify", {"agents": ["handoff", "sales"], "handoff_reason": "irritado"})
        decision = router.parse_decision(resp)
        assert decision.agents == ["handoff"]
        assert decision.handoff_reason == "irritado"

    def test_invalid_agent_names_filtered_out(self):
        resp = fake_function_call("classify", {"agents": ["not_a_real_agent", "booking"]})
        decision = router.parse_decision(resp)
        assert decision.agents == ["booking"]

    def test_duplicate_agent_names_deduped(self):
        resp = fake_function_call("classify", {"agents": ["sales", "sales", "booking"]})
        decision = router.parse_decision(resp)
        assert decision.agents == ["sales", "booking"]

    def test_more_than_two_agents_capped(self):
        resp = fake_function_call("classify", {"agents": ["sales", "booking", "handoff"]})
        decision = router.parse_decision(resp)
        # handoff filtered to sole item only if present after the cap; here
        # the cap takes the first two (sales, booking) before handoff is
        # ever considered, since we stop appending at 2.
        assert decision.agents == ["sales", "booking"]

    def test_empty_agents_falls_back_to_sales(self):
        resp = fake_function_call("classify", {"agents": []})
        decision = router.parse_decision(resp)
        assert decision.agents == ["sales"]

    def test_no_function_call_falls_back_to_sales(self):
        resp = fake_text("desculpe, não sei classificar")
        decision = router.parse_decision(resp)
        assert decision.agents == ["sales"]

    def test_no_candidates_falls_back_to_sales(self):
        resp = SimpleNamespace(candidates=[])
        decision = router.parse_decision(resp)
        assert decision.agents == ["sales"]


class TestClassify:
    async def test_single_gemini_call_forced_function(self):
        client = SequencedFakeClient([fake_function_call("classify", {"agents": ["booking"]})])
        decision = await router.classify(
            client=client,
            model="gemini-2.5-flash",
            tenant=_tenant(),
            contact=_contact(),
            new_message="tem horário quinta?",
            history=[],
            stage_value="returning_lead",
        )
        assert decision.agents == ["booking"]
        assert len(client.models.calls) == 1
        # Forced-function-call config must be present so Gemini can't reply in free text.
        config = client.models.calls[0]["config"]
        assert config.tool_config.function_calling_config.mode == "ANY"
        assert config.tool_config.function_calling_config.allowed_function_names == ["classify"]

"""
Tests for the per-clinic multi-agent switch (`ai.multi_agent_enabled_for`).

This is the flag the Settings → IA toggle writes
(`tenant.ai_config["multi_agent_enabled"]`). It decides whether a turn costs one
Gemini call (legacy single agent) or two to three (Router + specialist(s)), so
"which value wins" must be unambiguous: an explicit per-tenant boolean always
overrides the global default, and anything else falls back to the global.
"""

import uuid
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.ai import multi_agent_enabled_for


def _tenant(ai_config):
    return SimpleNamespace(id=uuid.uuid4(), name="Clínica", settings={}, ai_config=ai_config)


class TestMultiAgentEnabledFor:
    @pytest.mark.parametrize("global_default", [True, False])
    def test_explicit_tenant_value_wins_over_global(self, monkeypatch, global_default):
        monkeypatch.setattr(settings, "AI_MULTI_AGENT_ENABLED", global_default)
        assert multi_agent_enabled_for(_tenant({"multi_agent_enabled": True})) is True
        assert multi_agent_enabled_for(_tenant({"multi_agent_enabled": False})) is False

    @pytest.mark.parametrize("global_default", [True, False])
    def test_falls_back_to_global_when_tenant_has_no_opinion(self, monkeypatch, global_default):
        monkeypatch.setattr(settings, "AI_MULTI_AGENT_ENABLED", global_default)
        assert multi_agent_enabled_for(_tenant({})) is global_default
        assert multi_agent_enabled_for(_tenant(None)) is global_default
        assert multi_agent_enabled_for(_tenant({"model": "gemini-2.5-flash"})) is global_default

    def test_non_boolean_values_are_ignored_not_coerced(self, monkeypatch):
        # A truthy string like "false" must not silently enable the 3x-cost path.
        monkeypatch.setattr(settings, "AI_MULTI_AGENT_ENABLED", False)
        for junk in ("true", "false", 1, 0, [], "yes"):
            assert multi_agent_enabled_for(_tenant({"multi_agent_enabled": junk})) is False

    def test_default_is_off_so_enabling_is_always_deliberate(self):
        # Ships off: a clinic only pays the extra Gemini calls after someone
        # explicitly flips the toggle (Configurações → IA).
        assert settings.AI_MULTI_AGENT_ENABLED is False

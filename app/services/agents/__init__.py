"""
Multi-agent architecture for Sofia (Wave 3, feature-flagged via
AI_MULTI_AGENT_ENABLED / tenant.ai_config["multi_agent_enabled"]).

See app/services/agents/orchestrator.py for the entry point and
C:\\Users\\enzo.jz\\.claude\\plans\\drifting-tickling-creek.md for the design
rationale (why each rule lives where it lives, why hops are capped at 2, why
escalation discards rather than appends text).
"""

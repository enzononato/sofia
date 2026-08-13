"""
Testes da fonte única da janela de atendimento humano
(app/services/takeover.py). Puros — sem DB, sem rede, sem Gemini.

A regra vive em duas formas que precisam concordar: a função Python
(decisão por contato) e o predicado SQLAlchemy (filtro em query agregada,
usado pelo recovery sweep).
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.takeover import in_human_takeover, not_in_human_takeover_clause


def _now() -> datetime:
    return datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)


class TestInHumanTakeover:
    def test_true_while_the_window_is_open(self):
        now = _now()
        contact = SimpleNamespace(human_takeover_until=now + timedelta(minutes=30))
        assert in_human_takeover(contact, now) is True

    def test_false_once_the_window_expired(self):
        now = _now()
        contact = SimpleNamespace(human_takeover_until=now - timedelta(minutes=1))
        assert in_human_takeover(contact, now) is False

    def test_false_exactly_at_the_boundary(self):
        # Comparação estrita (until > now): no instante exato do vencimento a
        # janela já está fechada e a Sofia volta a responder.
        now = _now()
        contact = SimpleNamespace(human_takeover_until=now)
        assert in_human_takeover(contact, now) is False

    def test_false_when_never_set(self):
        contact = SimpleNamespace(human_takeover_until=None)
        assert in_human_takeover(contact, _now()) is False

    def test_false_when_the_attribute_is_missing(self):
        # Dublês de teste podem não declarar o campo — não pode levantar.
        assert in_human_takeover(SimpleNamespace(), _now()) is False


class TestNotInHumanTakeoverClause:
    def test_covers_both_cases_the_python_form_accepts(self):
        # O predicado é o complemento da função: passa quem nunca teve janela
        # (NULL) e quem já venceu (<= now).
        compiled = str(not_in_human_takeover_clause(_now()))
        assert "human_takeover_until IS NULL" in compiled
        assert "human_takeover_until <=" in compiled

    def test_is_an_or_of_exactly_two_conditions(self):
        compiled = str(not_in_human_takeover_clause(_now()))
        assert " OR " in compiled

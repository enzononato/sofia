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
    return datetime(2019, 3, 4, 12, 0, tzinfo=timezone.utc)


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
    def test_binds_the_injected_now_not_some_other_clock(self):
        # Compila com literal_binds para que o valor REAL de `now` apareça no
        # SQL. Sem isso o teste passaria mesmo se a cláusula ignorasse `now` e
        # consultasse um relógio próprio — que é exatamente a divergência entre
        # a forma Python e a forma SQL que este módulo existe para impedir.
        compiled = str(
            not_in_human_takeover_clause(_now()).compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        assert "2019-03-04" in compiled
        assert "human_takeover_until IS NULL" in compiled
        assert "human_takeover_until <=" in compiled

    def test_is_an_or_of_exactly_two_conditions(self):
        # Cardinalidade, não só presença de " OR ": um terceiro operando somado
        # no futuro violaria a equivalência com a forma Python sem quebrar um
        # teste de substring.
        clause = not_in_human_takeover_clause(_now())
        assert len(clause.clauses) == 2

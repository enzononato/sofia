"""
Fonte única da regra de "janela de atendimento humano" (item D4).

Quando alguém da equipe responde um paciente direto do próprio celular /
WhatsApp Web (evento com fromMe=true e wasSentByApi=false),
`Contact.human_takeover_until` recebe `now + HUMAN_TAKEOVER_PAUSE_MINUTES`.
Enquanto essa janela está aberta a Sofia não responde, e nenhum disparo
proativo (lembrete / reengajamento) sai para esse contato.

Distinta de `Contact.ai_paused`: esta janela EXPIRA sozinha assim que "now"
ultrapassa o timestamp — não existe ação de "despausar". Já `ai_paused` fica
até alguém da equipe limpar manualmente no Inbox.

Este módulo existe porque a mesma regra estava expressa em três lugares
(app/api/v1/routes/webhooks.py duas vezes — uma função e um predicado SQL — e
app/services/followups.py). Manter as duas formas lado a lado aqui faz de
qualquer mudança de semântica uma edição visível de duas linhas adjacentes,
em vez de três edições espalhadas que nada obriga a acontecer juntas.
"""

from datetime import datetime

from sqlalchemy import or_

from app.models.contact import Contact


def in_human_takeover(contact: Contact, now: datetime) -> bool:
    """
    True enquanto a equipe está atendendo este contato à mão.

    `now` é injetado (em vez de chamado aqui dentro) porque as guardas de
    disparo proativo em app/services/followups.py precisam avaliar a regra
    num instante controlado para testar fuso horário.

    O `getattr` defensivo é proposital: chamadores de teste passam dublês
    que podem não declarar o campo.
    """
    until = getattr(contact, "human_takeover_until", None)
    return until is not None and until > now


def not_in_human_takeover_clause(now: datetime):
    """
    A mesma regra, negada, como predicado SQLAlchemy — para queries agregadas
    que precisam filtrar contatos sem carregar cada um em Python (o recovery
    sweep roda como uma query só, não por contato).

    Deve permanecer o complemento exato de `in_human_takeover`: passa quem
    nunca teve janela (NULL) e quem já venceu (<= now).
    """
    return or_(
        Contact.human_takeover_until.is_(None),
        Contact.human_takeover_until <= now,
    )

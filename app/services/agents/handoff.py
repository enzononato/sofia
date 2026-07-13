"""
Handoff specialist: the ONLY agent allowed to call request_human_handoff
(pauses the AI on this contact, Contact.ai_paused=True — see
app/services/ai_tools.py::_request_human_handoff). Reached either directly
from the Router (unambiguous signal from the patient's message alone) or via
another specialist's escalate_to_human signal (see base.py's
run_specialist_loop and orchestrator.py's replace-not-append composition
rule — this agent's reply REPLACES whatever the escalating specialist had
started saying, it never gets appended to it).
"""

from app.services.agents.base import tools_subset

TOOL_NAMES: set[str] = {"request_human_handoff"}
TOOLS = tools_subset(TOOL_NAMES)

OVERLAY = """\
Você é a Sofia neste momento passando o atendimento para um humano da equipe. Isso acontece \
quando: o paciente pediu claramente para falar com uma pessoa, um humano, o dono ou "atendente \
de verdade"; ele está visivelmente irritado ou insatisfeito; relatou dor forte, alguma \
complicação após um procedimento ou uma urgência clínica; pediu algo fora do que a clínica pode \
resolver por aqui (desconto além do que os dados permitem, exceção de política, reclamação \
séria); ou depois de tentativas sem conseguir resolver a mesma coisa.

Chame request_human_handoff com um motivo curto e claro, e responda SÓ com uma despedida curta \
e acolhedora avisando que alguém da equipe já continua por ali (algo como "vou te passar pra \
alguém da equipe, já já continuam por aqui 😊"). Não tente resolver o problema de novo, não \
prometa prazo específico, não repita o que já foi dito antes na conversa — isso já fica com a \
equipe agora. Uma mensagem só, curta.\
"""

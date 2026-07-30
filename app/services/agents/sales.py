"""
Sales specialist: presenting services, pricing/payment questions, objection
handling, and CRM lead-temperature classification. Also the default/fallback
agent for ambiguous or general-chat turns (greetings, small talk), which is the
closest match to the legacy do-everything agent's opening behavior.

The sales technique itself is NOT written here: it lives in
app/services/prompts.py::SALES_PLAYBOOK, shared with the legacy single-agent
path so a fix lands in both. This module only adds what is specific to being a
specialist among others (scope) plus the CRM-classification duty, which is
Sales-only because `set_crm_stage` is Sales-only.
"""

from app.services.agents.base import tools_subset
from app.services.prompts import SALES_PLAYBOOK

TOOL_NAMES: set[str] = {
    "list_services",
    "get_clinic_info",
    "list_professionals",
    "set_crm_stage",
    # Read-only scheduling tools. Sales is the Router's DEFAULT agent, so it
    # must be able to answer "tem horário quinta?" and to register a patient
    # confirming a reminder ("sim, confirmo") — without these, that confirmation
    # was silently lost whenever the turn landed on the fallback route. Writing
    # to the schedule (create/reschedule/cancel) stays exclusive to Booking.
    "check_availability",
    "get_upcoming_appointments",
    "confirm_appointment",
}

TOOLS = tools_subset(TOOL_NAMES)

_SCOPE = """\
Você é a Sofia cuidando de APRESENTAR A CLÍNICA e de ajudar quem está decidindo agora: \
procedimentos, preços, formas de pagamento, políticas e quebra de objeção. Você consulta a \
agenda para responder sobre horários e registra a confirmação de presença de quem responde a um \
lembrete, mas não é você quem marca, remarca ou cancela.

Se o paciente já decidiu e só falta marcar, feche a sua parte e convide o próximo passo de forma \
concreta e verdadeira, do tipo perguntar qual dia fica melhor para ele. Nunca diga que já marcou, \
que já reservou ou que o agendamento "já está encaminhado", porque nada disso aconteceu. Nunca \
mencione outra pessoa, outro setor ou um sistema: para o paciente é sempre você.

CLASSIFICAÇÃO NO FUNIL: em todo turno em que o paciente der um sinal claro (interesse, hesitação, \
desinteresse), chame set_crm_stage na MESMA resposta em que você sonda ou responde. Sondar e \
classificar não são passos alternativos, acontecem juntos. Exceção importante: se o estágio atual \
já for 'scheduled', 'attended' ou 'post_care', NÃO reclassifique para hot_lead nem cold_lead, \
porque esses estágios são fatos (ele já marcou ou já veio) e não voltam atrás. Use 'lost' apenas \
se ele disser claramente que desistiu.\
"""

OVERLAY = f"{_SCOPE}\n\n{SALES_PLAYBOOK}"

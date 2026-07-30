"""
Booking specialist: everything about the schedule. Owns every WRITE tool that
touches an Appointment (create/reschedule/cancel/confirm) plus
update_contact_info (dominant real trigger is "peça o nome pra fechar" at the
end of the booking flow).

The booking flow itself is NOT written here: it lives in
app/services/prompts.py::BOOKING_PLAYBOOK, shared with the legacy single-agent
path so a fix lands in both. This module only adds what is specific to being a
specialist among others (scope).
"""

from app.services.agents.base import tools_subset
from app.services.prompts import BOOKING_PLAYBOOK

TOOL_NAMES: set[str] = {
    "check_availability",
    "create_appointment",
    "reschedule_appointment",
    "cancel_appointment",
    "confirm_appointment",
    "get_upcoming_appointments",
    "list_professionals",
    "list_services",
    "update_contact_info",
    # Read-only. A patient with a slot booked routinely asks "qual o endereço?"
    # or "aceita Pix?" mid-booking; without this the agent had no factual source
    # for it and would either stall or invent.
    "get_clinic_info",
}

TOOLS = tools_subset(TOOL_NAMES)

_SCOPE = """\
Você é a Sofia cuidando da AGENDA agora. Seu trabalho é marcar, remarcar, cancelar e confirmar \
horários. Não é sua parte apresentar procedimentos em detalhe nem conduzir uma negociação de \
preço: se o paciente puxar isso, responda o que for factual e simples com os dados que você tem \
e volte para o horário. Nunca diga que vai passar o assunto para outra pessoa, para outro setor \
ou para um sistema, e nunca prometa que alguém retorna depois: para o paciente é sempre você, do \
começo ao fim.\
"""

OVERLAY = f"{_SCOPE}\n\n{BOOKING_PLAYBOOK}"

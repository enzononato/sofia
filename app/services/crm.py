"""
CRM pipeline helpers — deterministic stage transitions.

The AI qualifies leads explicitly via the `set_crm_stage` tool (source="ai"),
classifying a NEW_LEAD as COLD_LEAD or HOT_LEAD once the conversation gives
enough signal. The team can drag cards by hand (source="manual"). On top of
that, a few *factual* events advance the stage deterministically so the Kanban
stays truthful even if the AI forgets:

  - appointment created    -> scheduled
  - appointment completed  -> attended

A brand-new lead is intentionally LEFT in `new_lead` on inbound — it only leaves
that column once Sofia (or the team) qualifies it. We do NOT auto-move it to a
"talking" stage anymore, since "is talking" says nothing about intent.

Manual moves are respected: an automatic transition never *regresses* a card and
never overrides a manual placement, EXCEPT a booked appointment (a hard fact)
which always moves the card forward to `scheduled`.
"""

from datetime import datetime, timezone

from app.models.contact import Contact, CrmStage


def _now() -> datetime:
    return datetime.now(timezone.utc)


def mark_inbound(contact: Contact) -> None:
    """Record inbound activity. Does NOT change the CRM stage: a new lead stays
    in 'new_lead' until Sofia qualifies it as cold/hot via set_crm_stage."""
    contact.last_inbound_at = _now()


# Stages that already reflect (or supersede) the given fact — leave them be.
_SCHEDULED_OR_PAST = {CrmStage.SCHEDULED.value, CrmStage.ATTENDED.value, CrmStage.POST_CARE.value}
_ATTENDED_OR_PAST = {CrmStage.ATTENDED.value, CrmStage.POST_CARE.value}


def mark_scheduled(contact: Contact) -> None:
    """A booked appointment is a hard fact — move to 'scheduled' unless the card
    is already there or further (attended/post_care). A 'lost' lead is revived."""
    if contact.crm_stage not in _SCHEDULED_OR_PAST:
        contact.crm_stage = CrmStage.SCHEDULED.value
        contact.crm_stage_source = "ai"
        contact.crm_stage_updated_at = _now()


def mark_attended(contact: Contact) -> None:
    """An appointment marked completed moves the card to 'attended'
    (unless already attended/post_care)."""
    if contact.crm_stage not in _ATTENDED_OR_PAST:
        contact.crm_stage = CrmStage.ATTENDED.value
        contact.crm_stage_source = "ai"
        contact.crm_stage_updated_at = _now()

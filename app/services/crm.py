"""
CRM pipeline helpers — deterministic stage transitions.

The AI moves cards explicitly via the `set_crm_stage` tool (source="ai"), and the
team can drag cards by hand (source="manual"). On top of that, a few *factual*
events advance the stage deterministically so the Kanban stays truthful even if
the AI forgets to classify:

  - inbound message from a brand-new lead  -> in_conversation
  - appointment created                    -> scheduled
  - appointment completed                  -> attended

Manual moves are respected: an automatic transition never *regresses* a card and
never overrides a manual placement, EXCEPT a booked appointment (a hard fact)
which always moves the card forward to `scheduled`.
"""

from datetime import datetime, timezone

from app.models.contact import Contact, CrmStage


def _now() -> datetime:
    return datetime.now(timezone.utc)


def mark_inbound(contact: Contact) -> None:
    """Record inbound activity; nudge a brand-new lead into 'in_conversation'.
    Never touches a manually-placed card."""
    contact.last_inbound_at = _now()
    if contact.crm_stage_source != "manual" and contact.crm_stage == CrmStage.NEW_LEAD.value:
        contact.crm_stage = CrmStage.IN_CONVERSATION.value
        contact.crm_stage_source = "ai"
        contact.crm_stage_updated_at = _now()


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

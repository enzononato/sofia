"""
Unit tests for app.services.crm (mark_inbound / mark_scheduled / mark_attended).

Contact is instantiated directly in memory (no DB session, no flush) — these
functions only read/write plain Python attributes on the object.
"""

from app.models.contact import Contact, CrmStage
from app.services.crm import mark_attended, mark_inbound, mark_scheduled


def _contact(stage: str, source: str = "ai") -> Contact:
    return Contact(full_name="Paciente Teste", crm_stage=stage, crm_stage_source=source)


def test_mark_inbound_sets_timestamp_but_never_changes_stage():
    contact = _contact(CrmStage.NEW_LEAD.value)
    assert contact.last_inbound_at is None

    mark_inbound(contact)

    assert contact.last_inbound_at is not None
    assert contact.crm_stage == CrmStage.NEW_LEAD.value


def test_mark_inbound_does_not_touch_stage_even_when_hot():
    contact = _contact(CrmStage.HOT_LEAD.value)
    mark_inbound(contact)
    assert contact.crm_stage == CrmStage.HOT_LEAD.value


def test_mark_scheduled_advances_from_new_lead():
    contact = _contact(CrmStage.NEW_LEAD.value)
    mark_scheduled(contact)
    assert contact.crm_stage == CrmStage.SCHEDULED.value
    assert contact.crm_stage_source == "ai"
    assert contact.crm_stage_updated_at is not None


def test_mark_scheduled_advances_from_cold_and_hot_lead():
    for stage in (CrmStage.COLD_LEAD.value, CrmStage.HOT_LEAD.value):
        contact = _contact(stage)
        mark_scheduled(contact)
        assert contact.crm_stage == CrmStage.SCHEDULED.value


def test_mark_scheduled_revives_lost_contact():
    contact = _contact(CrmStage.LOST.value)
    mark_scheduled(contact)
    assert contact.crm_stage == CrmStage.SCHEDULED.value


def test_mark_scheduled_does_not_regress_attended_or_post_care():
    for stage in (CrmStage.ATTENDED.value, CrmStage.POST_CARE.value):
        contact = _contact(stage, source="manual")
        mark_scheduled(contact)
        assert contact.crm_stage == stage
        # Untouched — source/timestamp shouldn't change either when we don't regress.
        assert contact.crm_stage_source == "manual"
        assert contact.crm_stage_updated_at is None


def test_mark_scheduled_does_not_regress_already_scheduled():
    contact = _contact(CrmStage.SCHEDULED.value, source="manual")
    mark_scheduled(contact)
    assert contact.crm_stage == CrmStage.SCHEDULED.value
    assert contact.crm_stage_source == "manual"


def test_mark_attended_advances_to_attended():
    contact = _contact(CrmStage.SCHEDULED.value)
    mark_attended(contact)
    assert contact.crm_stage == CrmStage.ATTENDED.value
    assert contact.crm_stage_source == "ai"
    assert contact.crm_stage_updated_at is not None


def test_mark_attended_does_not_regress_post_care():
    contact = _contact(CrmStage.POST_CARE.value, source="manual")
    mark_attended(contact)
    assert contact.crm_stage == CrmStage.POST_CARE.value
    assert contact.crm_stage_source == "manual"


def test_mark_attended_does_not_regress_already_attended():
    contact = _contact(CrmStage.ATTENDED.value, source="manual")
    mark_attended(contact)
    assert contact.crm_stage == CrmStage.ATTENDED.value
    assert contact.crm_stage_source == "manual"

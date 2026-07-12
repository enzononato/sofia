"""
LGPD data-subject-rights routes for a Contact — manual, staff-triggered only.

GET  /contacts/{id}/export      — full structured data export (read-only)
POST /contacts/{id}/anonymize   — irreversible PII scrub (destructive)

Both routes are tenant-scoped (contact must belong to CurrentTenantId) and
role-gated. No automated retention/deletion job exists anywhere in this
module — every call here is a direct, explicit action by an authenticated
clinic user acting on a patient's request.
"""

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentTenantId, CurrentUser, DBSession
from app.core.errors import ForbiddenError
from app.models.user import UserRole
from app.schemas.privacy import ContactAnonymizeResult, ContactExport
from app.services import privacy as privacy_service

router = APIRouter(prefix="/contacts", tags=["Privacy"])

# Export is read-only but still exposes full PII (incl. medical notes), so it
# follows the same roles as other contact-data-handling routes in contacts.py.
_EXPORT_ROLES = (UserRole.OWNER, UserRole.ADMIN, UserRole.RECEPTIONIST)

# Anonymization is irreversible and destructive — deliberately narrower than
# _EXPORT_ROLES / contacts.py's _WRITE_ROLES. Only OWNER/ADMIN can trigger it.
_ANONYMIZE_ROLES = (UserRole.OWNER, UserRole.ADMIN)


@router.get("/{contact_id}/export", response_model=ContactExport)
async def export_contact(
    contact_id: uuid.UUID,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """
    Return a full structured JSON export of everything the system holds
    about this contact: registration data, all messages, all appointments,
    and current CRM state. For handing over to a patient exercising an LGPD
    data-access/portability request. Read-only.
    """
    if current_user.role not in _EXPORT_ROLES:
        raise ForbiddenError("Insufficient permissions.")

    data = await privacy_service.export_contact_data(
        db, contact_id=contact_id, tenant_id=tenant_id, exported_by_user_id=current_user.id
    )
    return data


@router.post("/{contact_id}/anonymize", response_model=ContactAnonymizeResult)
async def anonymize_contact(
    contact_id: uuid.UUID,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """
    Irreversibly scrub this contact's PII (name, email, phone, date of
    birth, address, medical notes, WhatsApp profile data) and clear the
    text/media content of every message in its history, on the patient's
    request (LGPD "right to be forgotten").

    THIS CANNOT BE UNDONE. The contact row and its appointments/messages
    are kept (not deleted) so appointment history and reporting keep
    working, but all personal content is gone. Clearing `phone` also means
    a future WhatsApp message from this number will be treated as a brand
    new contact — see app/services/privacy.py for the full rationale.

    Restricted to OWNER/ADMIN (narrower than the usual write-role set)
    because of the destructive, irreversible nature of this action.
    """
    if current_user.role not in _ANONYMIZE_ROLES:
        raise ForbiddenError("Insufficient permissions.")

    result = await privacy_service.anonymize_contact(
        db, contact_id=contact_id, tenant_id=tenant_id, anonymized_by_user_id=current_user.id
    )
    return result

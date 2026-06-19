"""
Google Calendar integration — per-professional OAuth + event sync.

Design notes:
  - We persist only the encrypted OAuth *refresh* token (app/core/crypto.py).
  - The google-api-python-client is synchronous; all network calls are wrapped
    in asyncio.to_thread so they never block the event loop.
  - Every public function is best-effort: it logs and returns None/False on any
    failure (missing config, revoked token, API error) so calendar problems can
    never break booking. If GOOGLE_CLIENT_ID/SECRET are unset, the feature is off.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy import select

from app.config import settings
from app.core.crypto import decrypt
from app.database import AsyncSessionLocal
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.google_credentials import GoogleCalendarCredential
from app.models.service import Service
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

_DEFAULT_TZ = "America/Sao_Paulo"

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"


def is_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def _client_config() -> dict:
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }


# ── OAuth (sync helpers — call via asyncio.to_thread from async routes) ────────

def build_auth_url(state: str) -> str:
    flow = Flow.from_client_config(_client_config(), scopes=GOOGLE_SCOPES, state=state)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    url, _ = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    return url


def exchange_code(code: str) -> tuple[str | None, str]:
    """Returns (refresh_token, scope_string). refresh_token may be None if Google
    didn't return one (e.g. the user previously consented without prompt=consent)."""
    flow = Flow.from_client_config(_client_config(), scopes=GOOGLE_SCOPES)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    flow.fetch_token(code=code)
    creds = flow.credentials
    return creds.refresh_token, " ".join(creds.scopes or [])


# ── Event sync (sync helpers wrapped in to_thread) ─────────────────────────────

def _build_service(encrypted_refresh_token: str):
    creds = Credentials(
        token=None,
        refresh_token=decrypt(encrypted_refresh_token),
        token_uri=_TOKEN_URI,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=GOOGLE_SCOPES,
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _event_body(summary: str, description: str, start: datetime, end: datetime, tz: str) -> dict:
    return {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": tz},
        "end": {"dateTime": end.isoformat(), "timeZone": tz},
    }


async def create_event(
    encrypted_refresh_token: str, calendar_id: str,
    summary: str, description: str, start: datetime, end: datetime, tz: str,
) -> str | None:
    if not is_configured():
        return None

    def _do() -> str | None:
        service = _build_service(encrypted_refresh_token)
        event = service.events().insert(
            calendarId=calendar_id, body=_event_body(summary, description, start, end, tz)
        ).execute()
        return event.get("id")

    try:
        return await asyncio.to_thread(_do)
    except Exception:
        logger.exception("gcal_create_event_failed")
        return None


async def update_event(
    encrypted_refresh_token: str, calendar_id: str, event_id: str,
    summary: str, description: str, start: datetime, end: datetime, tz: str,
) -> bool:
    if not is_configured():
        return False

    def _do() -> bool:
        service = _build_service(encrypted_refresh_token)
        service.events().patch(
            calendarId=calendar_id, eventId=event_id,
            body=_event_body(summary, description, start, end, tz),
        ).execute()
        return True

    try:
        return await asyncio.to_thread(_do)
    except Exception:
        logger.exception("gcal_update_event_failed")
        return False


async def delete_event(encrypted_refresh_token: str, calendar_id: str, event_id: str) -> bool:
    if not is_configured():
        return False

    def _do() -> bool:
        service = _build_service(encrypted_refresh_token)
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return True

    try:
        return await asyncio.to_thread(_do)
    except Exception:
        logger.exception("gcal_delete_event_failed")
        return False


# ── High-level orchestration ───────────────────────────────────────────────────

async def sync_appointment(appointment_id: uuid.UUID) -> None:
    """
    Reflect an appointment in the assigned professional's Google Calendar.
    Opens its own DB session so it can run from background tasks or scheduler jobs.
    Best-effort: any failure is logged and swallowed. No-op when GCal is not
    configured, the appointment has no professional, or that professional hasn't
    connected their Google account.
    """
    if not is_configured():
        return

    async with AsyncSessionLocal() as db:
        try:
            appt = await db.get(Appointment, appointment_id)
            if appt is None or appt.professional_id is None:
                return

            cred = await db.scalar(
                select(GoogleCalendarCredential).where(
                    GoogleCalendarCredential.user_id == appt.professional_id
                )
            )
            if cred is None:
                return

            tenant = await db.get(Tenant, appt.tenant_id)
            tz = ((tenant.settings or {}).get("schedule", {}) or {}).get("timezone", _DEFAULT_TZ) if tenant else _DEFAULT_TZ

            contact = await db.get(Contact, appt.contact_id)
            service = await db.get(Service, appt.service_id) if appt.service_id else None
            summary = f"{service.name if service else 'Atendimento'} — {contact.full_name if contact else 'Paciente'}"
            description = appt.notes or ""
            start = appt.scheduled_at
            end = appt.ends_at or (start + timedelta(minutes=60))

            if appt.status == AppointmentStatus.CANCELLED:
                if appt.google_event_id:
                    await delete_event(cred.encrypted_refresh_token, cred.calendar_id, appt.google_event_id)
                    appt.google_event_id = None
            elif appt.google_event_id:
                await update_event(
                    cred.encrypted_refresh_token, cred.calendar_id, appt.google_event_id,
                    summary, description, start, end, tz,
                )
            else:
                event_id = await create_event(
                    cred.encrypted_refresh_token, cred.calendar_id,
                    summary, description, start, end, tz,
                )
                if event_id:
                    appt.google_event_id = event_id

            cred.last_sync_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("gcal_sync_appointment_failed", extra={"appointment_id": str(appointment_id)})


async def run_google_sync_reconcile() -> None:
    """
    Scheduler job: push to Google Calendar any future, non-cancelled appointment
    whose assigned professional has connected their calendar but which has no
    event id yet (covers AI-created bookings). Best-effort, capped per run.
    """
    if not is_configured():
        return
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        connected = (await db.execute(select(GoogleCalendarCredential.user_id))).scalars().all()
        if not connected:
            return
        appt_ids = (
            await db.execute(
                select(Appointment.id).where(
                    Appointment.scheduled_at > now,
                    Appointment.status != AppointmentStatus.CANCELLED,
                    Appointment.professional_id.in_(connected),
                    Appointment.google_event_id.is_(None),
                ).limit(50)
            )
        ).scalars().all()

    for appt_id in appt_ids:
        await sync_appointment(appt_id)

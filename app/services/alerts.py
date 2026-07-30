"""
Active alerts for the clinic team — emailed via app.services.email (Resend),
same tolerant pattern as staff invites: if RESEND_API_KEY isn't configured the
send is skipped (logged, not raised) so nothing here can ever break the AI
reply flow or a scheduler job.

Sofia herself never hands a conversation off to a human (that path was
removed — she resolves every turn on her own). So `contact.ai_paused` is now
set only by the AI-usage caps (a cost safety valve — see
webhooks.py::_ai_usage_caps_allow_reply) or manually by staff in the Inbox.
This module notifies the clinic by email when a contact ends up paused:
  - `send_handoff_alert_email` — fired by the per-contact usage cap the moment
    it trips (webhooks.py), so staff know a conversation went quiet.
  - the same function, in its "forgotten" flavor, is fired by
    app/services/followups.py::run_paused_alert when any paused contact has an
    unanswered inbound message sitting too long.
  - `send_tenant_usage_cap_alert_email` — the tenant-wide cap equivalent.
"""

import logging

from app.models.contact import Contact
from app.models.tenant import Tenant
from app.services.email import send_email

logger = logging.getLogger(__name__)


def _alert_email_enabled(tenant: Tenant) -> bool:
    """Per-tenant opt-out, tenant.settings.followups.handoff_alert_email_enabled.
    Defaults to True (enabled) when absent, matching the rest of the followups
    config (opt-out, not opt-in — see followups.py's `_followups_cfg` helpers)."""
    cfg = (tenant.settings or {}).get("followups", {}) or {}
    return cfg.get("handoff_alert_email_enabled", True) is not False


def _handoff_email_html(clinic_name: str, contact_name: str, contact_phone: str, reason: str) -> str:
    return f"""\
<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;color:#0f172a">
  <h2 style="color:#4f46e5">Um paciente está aguardando atendimento humano</h2>
  <p>A Sofia transferiu esta conversa da <strong>{clinic_name}</strong> para a equipe.</p>
  <table style="width:100%;border-collapse:collapse;margin:20px 0">
    <tr>
      <td style="padding:6px 0;color:#64748b;font-size:12px;width:110px">Paciente</td>
      <td style="padding:6px 0;font-size:14px;font-weight:600">{contact_name}</td>
    </tr>
    <tr>
      <td style="padding:6px 0;color:#64748b;font-size:12px">Telefone</td>
      <td style="padding:6px 0;font-size:14px;font-weight:600">{contact_phone}</td>
    </tr>
    <tr>
      <td style="padding:6px 0;color:#64748b;font-size:12px;vertical-align:top">Motivo</td>
      <td style="padding:6px 0;font-size:14px">{reason}</td>
    </tr>
  </table>
  <p style="font-size:13px">Entre no Inbox do sistema para responder a esse paciente.</p>
  <p style="font-size:11px;color:#94a3b8">Você pode desativar este e-mail em Configurações → Follow-ups.</p>
</div>"""


def _stale_email_html(clinic_name: str, contact_name: str, contact_phone: str, minutes: int) -> str:
    return f"""\
<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;color:#0f172a">
  <h2 style="color:#dc2626">Paciente aguardando há mais de {minutes} minutos</h2>
  <p>Este paciente da <strong>{clinic_name}</strong> foi transferido para atendimento humano e ainda não recebeu resposta.</p>
  <table style="width:100%;border-collapse:collapse;margin:20px 0">
    <tr>
      <td style="padding:6px 0;color:#64748b;font-size:12px;width:110px">Paciente</td>
      <td style="padding:6px 0;font-size:14px;font-weight:600">{contact_name}</td>
    </tr>
    <tr>
      <td style="padding:6px 0;color:#64748b;font-size:12px">Telefone</td>
      <td style="padding:6px 0;font-size:14px;font-weight:600">{contact_phone}</td>
    </tr>
  </table>
  <p style="font-size:13px">Ele está sem resposta desde então — dê uma olhada assim que possível.</p>
  <p style="font-size:11px;color:#94a3b8">Você pode desativar este e-mail em Configurações → Follow-ups.</p>
</div>"""


async def send_handoff_alert_email(
    tenant: Tenant,
    contact: Contact,
    reason: str | None,
    *,
    stale_minutes: int | None = None,
) -> bool:
    """
    Notify the clinic (tenant.email) that a patient needs human attention.

    Two flavors, selected by `stale_minutes`:
      - stale_minutes=None (default): "fresh" pause — the contact was just
        paused (today, only the per-contact AI-usage cap does this; see
        webhooks.py::_ai_usage_caps_allow_reply). `reason` is a short
        free-text explanation (may be None/empty).
      - stale_minutes=<int>: "forgotten" pause — the contact has been
        paused with an unanswered inbound message for at least that many
        minutes (see followups.py::run_paused_alert). `reason` is ignored
        in this flavor (the stale-duration template speaks for itself).

    Respects the per-tenant opt-out `tenant.settings.followups.handoff_alert_email_enabled`
    (default True). Never raises — `send_email()` already swallows/logs
    network errors and a missing RESEND_API_KEY, so this is safe to call
    fire-and-forget (e.g. via `asyncio.create_task`) from a hot path.

    Returns True if an email was actually dispatched, False if skipped
    (disabled by tenant, or no email provider configured) or failed.

    Always dispatched fire-and-forget (`asyncio.create_task`), never awaited —
    email has a 15s HTTP timeout and must not add latency to Sofia's reply or
    a scheduler job. Current call sites: the per-contact usage cap in
    webhooks.py::_ai_usage_caps_allow_reply (fresh flavor) and
    followups.py::run_paused_alert (forgotten flavor).

    Option B — app/api/v1/routes/webhooks.py::_generate_and_send, if Option A
      turns out awkward (e.g. because ai.py is under heavy concurrent edit).
      Capture `was_paused_before = contact.ai_paused` right after the contact
      is loaded (currently ~line 562-566, `contact = await db.scalar(...)`),
      then after `await ai_service.generate_reply(...)` + `await db.commit()`
      (currently ~line 583-591), check:
          if contact.ai_paused and not was_paused_before:
              asyncio.create_task(send_handoff_alert_email(tenant, contact, reason=None))
      Caveat: at this point the tool's free-text `reason` argument is no
      longer available (generate_reply doesn't return it), so this path can
      only pass `reason=None` unless generate_reply's return signature is
      also extended to surface it — Option A is strictly better for that
      reason, prefer it unless there's a concurrency conflict.
    ------------------------------------------------------------------
    """
    if not _alert_email_enabled(tenant):
        logger.info(
            "handoff_alert_email_disabled",
            extra={"tenant_id": str(tenant.id), "contact_id": str(contact.id)},
        )
        return False

    to = getattr(tenant, "email", None)
    if not to:
        logger.warning(
            "handoff_alert_email_no_recipient",
            extra={"tenant_id": str(tenant.id), "contact_id": str(contact.id)},
        )
        return False

    contact_name = contact.full_name or "Paciente"
    contact_phone = contact.phone or "(sem telefone)"

    if stale_minutes is not None:
        subject = f"⏳ Paciente aguardando há {stale_minutes}+ min — {contact_name}"
        html = _stale_email_html(tenant.name, contact_name, contact_phone, stale_minutes)
    else:
        subject = f"🔔 {contact_name} pediu atendimento humano"
        html = _handoff_email_html(tenant.name, contact_name, contact_phone, reason or "Não especificado.")

    sent = await send_email(to=to, subject=subject, html=html)
    logger.info(
        "handoff_alert_email_dispatched" if sent else "handoff_alert_email_skipped",
        extra={
            "tenant_id": str(tenant.id),
            "contact_id": str(contact.id),
            "stale": stale_minutes is not None,
        },
    )
    return sent


def _tenant_cap_email_html(clinic_name: str, count: int, cap: int) -> str:
    return f"""\
<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;color:#0f172a">
  <h2 style="color:#dc2626">Limite diário de respostas automáticas atingido</h2>
  <p>A <strong>{clinic_name}</strong> atingiu o limite diário de respostas automáticas da Sofia \
para TODA a clínica ({count} de {cap} permitidas hoje).</p>
  <p>As respostas automáticas foram pausadas para todos os pacientes até a equipe reativar \
manualmente, ou até o contador reiniciar amanhã.</p>
  <p style="font-size:13px">Entre no sistema para atender manualmente os pacientes pendentes, \
ou ajuste o limite diário se ele estiver baixo demais para o volume da clínica.</p>
</div>"""


async def send_tenant_usage_cap_alert_email(tenant: Tenant, count: int, cap: int) -> bool:
    """
    Notify the clinic that the WHOLE-TENANT daily AI-reply cap was exceeded
    (item D3 of the robustness plan) — Sofia's automatic replies are now
    paused for every contact in the clinic (`tenant.settings["ai_paused"]`,
    see app/api/v1/routes/webhooks.py::_tenant_ai_paused) until staff resume
    them or the daily count resets tomorrow.

    Deliberately a SEPARATE function from `send_handoff_alert_email` rather
    than widening that one's `contact: Contact` parameter to `Contact | None`:
    a tenant-wide cap has no single associated patient, and
    `send_handoff_alert_email` already has two call sites (app/services/ai.py,
    app/services/followups.py) that always pass a real Contact — keeping it
    unchanged avoids touching code owned by parallel workstreams. This
    function intentionally mirrors its shape (same opt-out flag, same
    never-raises/fire-and-forget contract) so both can be called the same way.

    Respects the same per-tenant opt-out as send_handoff_alert_email
    (tenant.settings.followups.handoff_alert_email_enabled, default True).
    Never raises — send_email() already swallows/logs failures — so this is
    safe to call fire-and-forget (asyncio.create_task) from a hot path.
    """
    if not _alert_email_enabled(tenant):
        logger.info("tenant_usage_cap_alert_email_disabled", extra={"tenant_id": str(tenant.id)})
        return False

    to = getattr(tenant, "email", None)
    if not to:
        logger.warning("tenant_usage_cap_alert_email_no_recipient", extra={"tenant_id": str(tenant.id)})
        return False

    subject = f"🚨 Limite diário de respostas automáticas atingido — {tenant.name}"
    html = _tenant_cap_email_html(tenant.name, count, cap)

    sent = await send_email(to=to, subject=subject, html=html)
    logger.info(
        "tenant_usage_cap_alert_email_dispatched" if sent else "tenant_usage_cap_alert_email_skipped",
        extra={"tenant_id": str(tenant.id), "count": count, "cap": cap},
    )
    return sent

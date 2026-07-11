"""
Active alerts for the clinic team — emailed via app.services.email (Resend),
same tolerant pattern as staff invites: if RESEND_API_KEY isn't configured the
send is skipped (logged, not raised) so nothing here can ever break the AI
reply flow or a scheduler job.

Today this covers the human-handoff alert (item 3.1 / 3.2 of the robustness
plan): when Sofia hands a conversation off to a human (`request_human_handoff`
in app/services/ai_tools.py, which sets `contact.ai_paused = True`), the
clinic should be notified by email instead of relying on someone noticing the
passive badge in the Inbox. A second alert fires if the contact stays paused
with an unanswered inbound message for too long (see
app/services/followups.py::run_paused_alert).

NOT wired into the AI tool-call flow yet — see the docstring on
`send_handoff_alert_email` for exactly where to call it from.
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
      - stale_minutes=None (default): "fresh" handoff — Sofia just paused
        herself on this contact. `reason` is the free-text `reason` argument
        the AI passed to `request_human_handoff` (may be None/empty).
      - stale_minutes=<int>: "forgotten" handoff — the contact has been
        paused with an unanswered inbound message for at least that many
        minutes (see followups.py::run_paused_alert). `reason` is ignored
        in this flavor (the stale-duration template speaks for itself).

    Respects the per-tenant opt-out `tenant.settings.followups.handoff_alert_email_enabled`
    (default True). Never raises — `send_email()` already swallows/logs
    network errors and a missing RESEND_API_KEY, so this is safe to call
    fire-and-forget (e.g. via `asyncio.create_task`) from a hot path.

    Returns True if an email was actually dispatched, False if skipped
    (disabled by tenant, or no email provider configured) or failed.

    ------------------------------------------------------------------
    WIRING NOTE (not done in this change — see plan constraints): this
    function is not yet called anywhere. The other workstream owns
    app/services/ai_tools.py and app/api/v1/routes/webhooks.py; connect it
    there during the merge step:

    Option A (preferred) — app/services/ai.py::generate_reply, right after
      the tool-execution block that already exists around the line:
          tool_result = await execute_tool(
              name=fn.name, args=dict(fn.args), db=db,
              tenant_id=..., contact_id=..., ...
          )
      (currently ~line 634-643 in app/services/ai.py). Add immediately
      after that call, before the `logger.info("ai_tool_executed", ...)`
      block:
          if fn.name == "request_human_handoff" and tool_result.get("success"):
              import asyncio
              from app.services.alerts import send_handoff_alert_email
              asyncio.create_task(
                  send_handoff_alert_email(tenant, contact, dict(fn.args).get("reason"))
              )
      Use `asyncio.create_task` (fire-and-forget), NOT `await` — email has a
      15s HTTP timeout and must never add latency to Sofia's reply. `tenant`
      and `contact` are already in scope in `generate_reply`; `dict(fn.args)`
      gives the `reason` the AI passed to the tool.

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

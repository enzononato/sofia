"""
Transactional email via Resend (https://resend.com).

Graceful degradation: if RESEND_API_KEY is not configured the function logs and
returns False instead of raising — callers (e.g. the invite flow) then fall back
to showing the link so the admin can deliver it manually. No email infra is
required to use the product.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_RESEND_ENDPOINT = "https://api.resend.com/emails"


async def send_email(to: str, subject: str, html: str) -> bool:
    """Send an email. Returns True if dispatched, False if skipped/failed."""
    if not settings.RESEND_API_KEY:
        logger.info("email_skipped_no_provider", extra={"to": to, "subject": subject})
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _RESEND_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.MAIL_FROM,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
            )
        if resp.status_code >= 400:
            logger.warning(
                "email_send_failed",
                extra={"to": to, "status": resp.status_code, "body": resp.text[:300]},
            )
            return False
        logger.info("email_sent", extra={"to": to, "subject": subject})
        return True
    except Exception:
        logger.exception("email_send_error", extra={"to": to})
        return False


def invite_email_html(clinic_name: str, role_label: str, invite_link: str) -> str:
    """Simple, provider-agnostic HTML body for a staff invitation."""
    return f"""\
<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;color:#0f172a">
  <h2 style="color:#4f46e5">Você foi convidado para a {clinic_name}</h2>
  <p>Você recebeu um convite para acessar o sistema como <strong>{role_label}</strong>.</p>
  <p>Para ativar seu acesso e definir sua senha, clique no botão abaixo:</p>
  <p style="text-align:center;margin:28px 0">
    <a href="{invite_link}" style="background:#4f46e5;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600">
      Ativar meu acesso
    </a>
  </p>
  <p style="font-size:12px;color:#64748b">Se o botão não funcionar, copie e cole este link no navegador:<br>{invite_link}</p>
  <p style="font-size:12px;color:#64748b">Este convite expira em alguns dias.</p>
</div>"""

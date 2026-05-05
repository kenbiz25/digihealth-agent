"""
Email Service - Sends the PDF report and transactional emails via SMTP.
Supports Gmail, SendGrid, and standard SMTP.
"""
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from backend.config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    EMAIL_FROM, EMAIL_TO, EMAIL_ENABLED
)


_IMPACT_COLOR = {"critical": "#CF222E", "high": "#BC4C00", "medium": "#0969DA", "low": "#8C959F"}
_IMPACT_LABEL = {"critical": "🔴 Critical", "high": "🟠 High", "medium": "🔵 Medium", "low": "⚪ Low"}


def _smtp_send(msg: MIMEMultipart, recipients: list[str]) -> bool:
    """Open SMTP connection and send. Returns True on success."""
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(msg["From"], recipients, msg.as_string())
        return True
    except Exception as e:
        print(f"[Email] SMTP error: {e}")
        return False


def _smtp_ready() -> bool:
    return bool(SMTP_USER and SMTP_PASSWORD)


async def send_email(pdf_path: str, report_title: str, to_email: str | None = None) -> bool:
    """Kept for backwards compatibility — wraps send_digest_summary_email with no articles."""
    return await send_digest_summary_email(
        to_email=to_email or EMAIL_TO,
        articles=[],
        run_meta={"trigger": "scheduled", "countries": [], "run_date": datetime.utcnow().strftime("%B %d, %Y"), "next_run": ""},
    )


async def send_digest_summary_email(
    to_email: str,
    articles: list[dict],
    run_meta: dict,
    pdf_path: str | None = None,
) -> bool:
    """Send a digest email with article highlights and links.

    run_meta keys: trigger, countries (list), run_date, next_run
    """
    if not _smtp_ready():
        print(f"[Email] SMTP not configured — skipping digest to {to_email}")
        return False
    if not to_email:
        return False

    trigger    = run_meta.get("trigger", "scheduled")
    countries  = run_meta.get("countries") or []
    run_date   = run_meta.get("run_date") or datetime.utcnow().strftime("%B %d, %Y")
    next_run   = run_meta.get("next_run") or ""

    is_manual  = trigger == "manual"
    scope_line = (f"Manual scan — {', '.join(countries)}" if countries else "Manual scan — all countries") if is_manual else "Scheduled scan — all countries"
    badge_bg   = "#fff8f0" if is_manual else "#f0f4ff"
    badge_bd   = "#BC4C00" if is_manual else "#4B48E5"

    # Group articles
    by_impact: dict[str, list] = {"critical": [], "high": [], "medium": [], "low": []}
    for a in articles:
        lvl = a.get("impact_level") or "low"
        if lvl in by_impact:
            by_impact[lvl].append(a)

    def _article_row(a: dict, show_badge: bool = True) -> str:
        lvl   = a.get("impact_level") or "low"
        color = _IMPACT_COLOR.get(lvl, "#8C959F")
        label = _IMPACT_LABEL.get(lvl, lvl.title())
        title = a.get("executive_headline") or a.get("title") or "Untitled"
        url   = a.get("url") or "#"
        src   = a.get("source_name") or ""
        summ  = (a.get("summary") or "")[:160]
        ctry  = ", ".join(a.get("countries_mentioned") or [])
        badge = f'<span style="font-size:10px;font-weight:700;color:{color}">{label}</span>&nbsp;' if show_badge else ''
        return f"""
        <tr>
          <td style="padding:10px 0;border-bottom:1px solid #f0f0f0;vertical-align:top">
            {badge}<a href="{url}" style="font-size:14px;font-weight:600;color:#1B4F72;text-decoration:none">{title}</a>
            <div style="font-size:12px;color:#6B7280;margin-top:2px">{src}{' · '+ctry if ctry else ''}</div>
            {f'<div style="font-size:12px;color:#374151;margin-top:4px">{summ}</div>' if summ else ''}
          </td>
        </tr>"""

    def _section(level: str, arts: list) -> str:
        if not arts:
            return ""
        color = _IMPACT_COLOR.get(level, "#8C959F")
        label = _IMPACT_LABEL.get(level, level.title())
        rows  = "".join(_article_row(a, show_badge=False) for a in arts[:10])
        return f"""
        <div style="margin-bottom:24px">
          <h3 style="margin:0 0 8px;font-size:13px;font-weight:700;color:{color};text-transform:uppercase;letter-spacing:.5px">{label} ({len(arts)})</h3>
          <table style="width:100%;border-collapse:collapse">{rows}</table>
        </div>"""

    total = len(articles)
    n_crit = len(by_impact["critical"])
    highlights = _section("critical", by_impact["critical"]) + _section("high", by_impact["high"])
    other_rows = "".join(_article_row(a) for a in (by_impact["medium"] + by_impact["low"])[:15])
    other_section = f"""
      <div style="margin-bottom:24px">
        <h3 style="margin:0 0 8px;font-size:13px;font-weight:700;color:#374151;text-transform:uppercase;letter-spacing:.5px">Other coverage</h3>
        <table style="width:100%;border-collapse:collapse">{other_rows}</table>
      </div>""" if other_rows else ""

    alert_banner = f"""
      <div style="background:#FEF2F2;border-left:4px solid #CF222E;padding:12px 16px;margin-bottom:20px;border-radius:0 6px 6px 0">
        <strong style="color:#CF222E">⚠ {n_crit} critical alert{'s' if n_crit!=1 else ''} require attention</strong>
      </div>""" if n_crit else ""

    next_run_line = f'<p style="margin:4px 0 0;font-size:11px;color:#6B7280">Next scan: {next_run}</p>' if next_run else ""

    html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;color:#2C3E50;background:#f8f9fa;padding:0">
  <div style="background:#1B4F72;padding:20px 24px">
    <h1 style="color:#fff;margin:0;font-size:18px;font-weight:700">Medtronic Labs</h1>
    <p style="color:#AED6F1;margin:4px 0 0;font-size:13px">Digital Health Scanner — Intelligence Digest</p>
  </div>
  <div style="background:{badge_bg};border-left:4px solid {badge_bd};padding:12px 24px;font-size:13px">
    <strong>{scope_line}</strong> &nbsp;·&nbsp; {run_date}
  </div>
  <div style="background:#fff;padding:24px">
    <p style="font-size:13px;color:#6B7280;margin:0 0 16px">{total} article{'s' if total!=1 else ''} verified &nbsp;·&nbsp; {len(by_impact['critical'])} critical &nbsp;·&nbsp; {len(by_impact['high'])} high priority</p>
    {alert_banner}
    {highlights}
    {other_section}
    <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
    <p style="font-size:11px;color:#9CA3AF;margin:0">Generated {run_date} · Medtronic Labs Digital Health Scanner</p>
    {next_run_line}
  </div>
</body></html>"""

    msg = MIMEMultipart("mixed")
    msg["From"] = EMAIL_FROM or SMTP_USER
    msg["To"] = to_email
    flag = "Manual" if is_manual else "Digest"
    msg["Subject"] = f"[M.LABS] {flag}: Digital Health Intelligence — {run_date}"

    # HTML body wrapped in alternative sub-part
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html, "html"))
    msg.attach(alt)

    # PDF attachment
    if pdf_path and os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
            part = MIMEBase("application", "pdf")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        pdf_name = os.path.basename(pdf_path)
        part.add_header("Content-Disposition", "attachment", filename=pdf_name)
        msg.attach(part)

    ok = _smtp_send(msg, [to_email])
    if ok:
        print(f"[Email] Digest sent to {to_email} ({total} articles, trigger={trigger}, pdf={'yes' if pdf_path else 'no'})")
    return ok


async def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    """Send a password-reset link. Works even when EMAIL_ENABLED=false."""
    if not _smtp_ready():
        print(f"[Email] SMTP not configured — reset URL: {reset_url}")
        return False

    html = f"""
<html><body style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;color:#2C3E50">
  <div style="background:#1B4F72;padding:24px;text-align:center">
    <h1 style="color:#fff;margin:0;font-size:20px">Medtronic Labs</h1>
    <p style="color:#AED6F1;margin:4px 0 0">Digital Health Scanner</p>
  </div>
  <div style="padding:32px;background:#f8f9fa">
    <h2 style="color:#1B4F72">Reset your password</h2>
    <p>We received a request to reset the password for <strong>{to_email}</strong>.</p>
    <p>Click the button below to set a new password. This link expires in <strong>1 hour</strong>.</p>
    <div style="text-align:center;margin:32px 0">
      <a href="{reset_url}" style="background:#4B48E5;color:#fff;text-decoration:none;
         padding:14px 28px;border-radius:8px;font-size:15px;font-weight:600">
        Reset password
      </a>
    </div>
    <p style="font-size:12px;color:#7F8C8D">
      If you didn't request this, ignore this email — your password won't change.<br>
      Link: {reset_url}
    </p>
  </div>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["From"] = EMAIL_FROM or SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = "Reset your Medtronic Labs password"
    msg.attach(MIMEText(html, "html"))

    ok = _smtp_send(msg, [to_email])
    if ok:
        print(f"[Email] Password reset sent to {to_email}")
    return ok

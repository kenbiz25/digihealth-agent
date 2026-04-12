"""
Email Service - Sends the PDF report via SMTP.
Supports Gmail, SendGrid, and standard SMTP.
"""
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from datetime import datetime
from backend.config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    EMAIL_FROM, EMAIL_TO, EMAIL_ENABLED
)


EMAIL_BODY_HTML = """
<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #2C3E50;">
  <div style="background: #1B4F72; padding: 24px; text-align: center;">
    <h1 style="color: white; margin: 0; font-size: 20px;">Digi-Health Intelligence</h1>
    <p style="color: #AED6F1; margin: 4px 0 0;">7-Day Country Brief</p>
  </div>
  <div style="padding: 24px; background: #f8f9fa;">
    <h2 style="color: #1B4F72;">{title}</h2>
    <p>Your weekly AI-curated intelligence brief covering digital health across Sierra Leone, Bangladesh, Kenya, Rwanda, Ghana, India, Saudi Arabia, Tanzania and Bhutan is ready.</p>
    <div style="background: white; border-left: 4px solid #3DBFAA; padding: 16px; margin: 16px 0;">
      <p style="margin: 0; font-size: 14px;"><strong>What's inside:</strong></p>
      <ul style="margin: 8px 0; font-size: 13px;">
        <li>One-page executive snapshot per country (last 7 days)</li>
        <li>Official ministry and minister pronouncements</li>
        <li>Social sentiment from LinkedIn and Twitter</li>
        <li>Impact-classified headlines with recommended executive actions</li>
      </ul>
    </div>
    <p>See the attached PDF for the full report.</p>
    <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
    <p style="font-size: 11px; color: #7F8C8D;">
      Generated at {date} UTC by Digi-Health AI Agent<br>
      Powered by Anthropic Claude
    </p>
  </div>
</body>
</html>
"""


async def send_email(pdf_path: str, report_title: str) -> bool:
    """Send the PDF report via email. Returns True if successful."""
    if not EMAIL_ENABLED:
        print("[Email] EMAIL_ENABLED=false, skipping send.")
        return False

    if not all([SMTP_USER, SMTP_PASSWORD, EMAIL_TO]):
        print("[Email] Missing SMTP credentials or recipient. Check .env")
        return False

    if not os.path.exists(pdf_path):
        print(f"[Email] PDF not found at: {pdf_path}")
        return False

    recipients = [r.strip() for r in EMAIL_TO.split(",") if r.strip()]
    date_str = datetime.utcnow().strftime("%B %d, %Y")
    subject = f"[Digital Health Africa] {report_title}"

    msg = MIMEMultipart("mixed")
    msg["From"] = EMAIL_FROM or SMTP_USER
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject

    # HTML body
    html_body = EMAIL_BODY_HTML.format(title=report_title, date=date_str)
    msg.attach(MIMEText(html_body, "html"))

    # Attach PDF
    with open(pdf_path, "rb") as f:
        part = MIMEBase("application", "pdf")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    filename = os.path.basename(pdf_path)
    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    msg.attach(part)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(msg["From"], recipients, msg.as_string())
        print(f"[Email] Sent to {recipients}")
        return True
    except Exception as e:
        print(f"[Email] Failed to send: {e}")
        return False

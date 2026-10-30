import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger("marketingos.email")

# Development/test outbox: the console backend keeps the last messages here.
OUTBOX: list[dict] = []


def send_email(to: str, subject: str, text: str) -> None:
    settings = get_settings()
    if settings.email_backend == "smtp" and settings.smtp_host:
        msg = EmailMessage()
        msg["From"] = settings.email_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password or "")
            smtp.send_message(msg)
        return
    OUTBOX.append({"to": to, "subject": subject, "text": text})
    del OUTBOX[:-50]
    log.info("email to=%s subject=%s\n%s", to, subject, text)

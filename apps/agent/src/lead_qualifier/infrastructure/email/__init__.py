"""Email senders. ``EMAIL_PROVIDER`` picks one: ``smtp`` (default, Mailpit) or ``resend``."""

from __future__ import annotations

from lead_qualifier.config import Settings
from lead_qualifier.infrastructure.email.resend import ResendSender
from lead_qualifier.infrastructure.email.smtp import SmtpSender
from lead_qualifier.ports.channel import EmailSender


def build_email_sender(settings: Settings) -> EmailSender:
    if settings.email_provider == "resend":
        return ResendSender(settings.resend_api_key.get_secret_value())
    return SmtpSender(
        settings.smtp_host,
        settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password.get_secret_value(),
        starttls=settings.smtp_starttls,
        use_ssl=settings.smtp_ssl,
    )

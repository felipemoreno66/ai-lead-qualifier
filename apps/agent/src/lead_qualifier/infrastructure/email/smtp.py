"""SMTP sender (Mailpit locally; any SMTP server in production)."""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate

from lead_qualifier.domain.channel import sanitize_header, strip_invisible
from lead_qualifier.ports.channel import ChannelPayload, EmailSendError


class SmtpSender:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        username: str = "",
        password: str = "",
        starttls: bool = False,
        use_ssl: bool = False,
        timeout: float = 15.0,
    ) -> None:
        if username and not (starttls or use_ssl):
            raise ValueError("refusing to log in to SMTP without STARTTLS or SSL")
        self.host, self.port = host, port
        self.username, self.password = username, password
        self.starttls, self.use_ssl, self.timeout = starttls, use_ssl, timeout

    def _build(self, payload: ChannelPayload) -> EmailMessage:
        message = EmailMessage()
        message["From"] = payload.sender
        message["To"] = payload.recipient
        message["Subject"] = sanitize_header(payload.subject)  # defence in depth
        message["Message-ID"] = payload.message_id
        message["Date"] = formatdate(usegmt=True)
        message.set_content(strip_invisible(payload.text))  # text/plain only
        return message

    def _send_blocking(self, payload: ChannelPayload) -> None:
        message = self._build(payload)
        context = ssl.create_default_context()
        if self.use_ssl:
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                self.host, self.port, timeout=self.timeout, context=context
            )
        else:
            smtp = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        with smtp:
            if self.starttls and not self.use_ssl:
                smtp.starttls(context=context)
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)

    async def send(self, payload: ChannelPayload) -> str:
        try:
            await asyncio.to_thread(self._send_blocking, payload)
        except smtplib.SMTPResponseException as exc:
            # The text can contain the recipient's address: keep only the class and the code.
            raise EmailSendError(
                f"{type(exc).__name__} {exc.smtp_code}", transient=400 <= exc.smtp_code < 500
            ) from exc
        except smtplib.SMTPRecipientsRefused as exc:
            codes = {code for code, _ in exc.recipients.values()}
            raise EmailSendError(
                "SMTPRecipientsRefused",
                transient=bool(codes) and all(400 <= c < 500 for c in codes),
            ) from exc
        except (OSError, smtplib.SMTPException) as exc:  # timeouts, refused connections, drops
            raise EmailSendError(type(exc).__name__, transient=True) from exc
        return payload.message_id

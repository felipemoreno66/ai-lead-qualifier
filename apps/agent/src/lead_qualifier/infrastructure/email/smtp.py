"""SMTP sender (Mailpit locally; any SMTP server in production)."""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage

from lead_qualifier.domain.channel import sanitize_header
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
        timeout: float = 15.0,
    ) -> None:
        self.host, self.port = host, port
        self.username, self.password = username, password
        self.starttls, self.timeout = starttls, timeout

    def _send_blocking(self, payload: ChannelPayload) -> None:
        message = EmailMessage()
        message["From"] = payload.sender
        message["To"] = payload.recipient
        message["Subject"] = sanitize_header(payload.subject)  # defence in depth
        message["Message-ID"] = payload.message_id
        message.set_content(payload.text)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
            if self.starttls:
                smtp.starttls(context=ssl.create_default_context())
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)

    async def send(self, payload: ChannelPayload) -> str:
        try:
            await asyncio.to_thread(self._send_blocking, payload)
        except (OSError, smtplib.SMTPException) as exc:
            # The exception text can contain the recipient address: keep only its type.
            raise EmailSendError(type(exc).__name__) from exc
        return payload.message_id

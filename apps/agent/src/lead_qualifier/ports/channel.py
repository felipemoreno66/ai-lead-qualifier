"""Outbound message channels. Only email exists; WhatsApp would add a second implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChannelMessage:
    """An approved message, as stored: what a channel needs to build its payload."""

    id: str
    channel: str
    recipient: str
    subject: str | None
    body: str
    short_body: str | None
    language: str


@dataclass(frozen=True)
class ChannelPayload:
    """A ready-to-send message. ``message_id`` is stable per stored message so a redelivery
    can be recognised by the receiver."""

    channel: str
    sender: str
    recipient: str
    subject: str
    text: str
    message_id: str


class UnsupportedChannel(Exception):
    """The message's channel has no implementation (for example ``whatsapp`` for now)."""


class MessageChannel(Protocol):
    name: str

    def validate_recipient(self, recipient: str) -> None:
        """Raise ``ValueError`` when ``recipient`` is not usable on this channel."""

    def render(self, message: ChannelMessage) -> ChannelPayload: ...


class EmailSender(Protocol):
    async def send(self, payload: ChannelPayload) -> str:
        """Deliver ``payload``; return the provider message id. Raise ``EmailSendError``."""
        ...


class EmailSendError(Exception):
    """The email could not be delivered. Carries no recipient data."""

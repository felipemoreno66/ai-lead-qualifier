"""Channel implementations that need no I/O: validation and rendering."""

from __future__ import annotations

import re
import unicodedata
from email.utils import parseaddr

from lead_qualifier.domain.draft_guard import has_unsafe_chars
from lead_qualifier.domain.workspace import EMAIL_RE
from lead_qualifier.ports.channel import (
    ChannelMessage,
    ChannelPayload,
    MessageChannel,
    UnsupportedChannel,
)


def sanitize_header(text: str) -> str:
    """One line without control or bidirectional characters: a header can never be split."""
    cleaned = "".join(
        " " if has_unsafe_chars(c, allow_newlines=False) or unicodedata.category(c) == "Cc" else c
        for c in text
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def strip_invisible(text: str) -> str:
    """Remove control, bidirectional and other invisible format characters, keeping line breaks."""
    return "".join(
        c
        for c in text
        if c in "\n\t" or not (has_unsafe_chars(c, allow_newlines=False) or c == "\r")
    )


class EmailChannel:
    name = "email"

    def __init__(
        self,
        sender: str,
        message_id_domain: str = "lead-qualifier.local",
        reply_to: str | None = None,
    ) -> None:
        self.sender = sender
        self.reply_to = reply_to
        self.message_id_domain = message_id_domain

    def validate_recipient(self, recipient: str) -> None:
        # fullmatch: "$" would also accept a trailing newline; parseaddr must read it back unchanged
        if not EMAIL_RE.fullmatch(recipient) or parseaddr(recipient)[1] != recipient:
            raise ValueError("the recipient is not a valid email address")

    def render(self, message: ChannelMessage) -> ChannelPayload:
        self.validate_recipient(message.recipient)
        if not message.subject or not sanitize_header(message.subject):
            raise ValueError("an email needs a subject")
        return ChannelPayload(
            channel=self.name,
            sender=self.sender,
            recipient=message.recipient,
            subject=sanitize_header(message.subject),
            text=message.body,
            message_id=f"<{message.id}@{self.message_id_domain}>",
            reply_to=self.reply_to,
        )


def channel_for(name: str, *, sender: str, reply_to: str | None = None) -> MessageChannel:
    """The channel implementation for ``name``; only email is built."""
    if name == "email":
        return EmailChannel(sender, reply_to=reply_to)
    raise UnsupportedChannel(name)

"""Wire format of the public lead submission (``POST /api/leads/{slug}``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LeadSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: dict[str, Any]
    consent: bool
    consent_notice_version: str = Field(min_length=1, max_length=40)
    locale: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    hp_company_website: str = Field(default="", max_length=500)
    form_rendered_at: datetime | None = None


class LeadAccepted(BaseModel):
    received: bool = True
    reference: str

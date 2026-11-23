"""Lead intake use case: validate, de-duplicate and persist lead + event + outbox atomically."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.config import Settings
from lead_qualifier.domain.errors import ConsentOutdated, ValidationFailed
from lead_qualifier.domain.lead_form import validate_answers
from lead_qualifier.domain.lead_intake import LeadSubmission
from lead_qualifier.domain.workspace import FieldRole, FieldType, WorkspaceConfig
from lead_qualifier.infrastructure.db.repositories import LeadRepository, OutboxRepository
from lead_qualifier.logging import get_logger
from lead_qualifier.ports.clock import Clock
from lead_qualifier.security import hash_value
from lead_qualifier.services.rate_limit import Limit, RateLimiter

log = get_logger("intake")

REFERENCE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
REFERENCE_LENGTH = 6
USER_AGENT_MAX = 256


@dataclass(frozen=True)
class RequestMeta:
    ip_hash: str
    origin: str | None
    user_agent: str | None
    source: str


def reference_prefix(config: WorkspaceConfig) -> str:
    """Public reference prefix: configured, else the initials of the slug (``ab-cd`` -> ``AC``)."""
    if config.profile.reference_prefix:
        return config.profile.reference_prefix
    return "".join(part[0] for part in config.slug.split("-") if part).upper()[:4] or "LD"


def new_reference(config: WorkspaceConfig) -> str:
    suffix = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(REFERENCE_LENGTH))
    return f"{reference_prefix(config)}-{suffix}"


class IntakeService:
    def __init__(
        self, engine: AsyncEngine, settings: Settings, clock: Clock, limiter: RateLimiter
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.clock = clock
        self.limiter = limiter

    async def submit(
        self, config: WorkspaceConfig, submission: LeadSubmission, meta: RequestMeta
    ) -> str:
        """Return the public reference. Spam is acknowledged but never stored."""
        slug = config.slug
        if self._is_spam(submission):
            log.info("spam_blocked", workspace=slug)
            return new_reference(config)

        self._check_consent(config, submission)
        clean, field_errors = validate_answers(config.form.fields, submission.fields)
        if field_errors:
            raise ValidationFailed(
                "Some fields are invalid.",
                errors=[{"loc": ["fields", e.field], "msg": e.message} for e in field_errors],
            )

        email = str(clean[_role_field(config, FieldRole.EMAIL)])
        now = self.clock.now()
        window = timedelta(minutes=self.settings.duplicate_window_minutes)
        if window:
            async with self.engine.connect() as conn:
                duplicate = await LeadRepository(conn).find_recent_duplicate(
                    slug, email, now - window
                )
            if duplicate:
                log.info("duplicate_submission", workspace=slug, lead_id=str(duplicate["id"]))
                # Never reveal the stored reference: that would let anyone who knows an
                # email address learn another person's lead reference.
                return new_reference(config)

        await self.limiter.hit(
            [
                Limit(
                    f"email:{slug}:{hash_value(email, self.settings.ip_hash_secret)}",
                    self.settings.rate_email_per_day,
                    86400,
                ),
                # Last, so only requests that passed the per-IP and per-email limits and
                # validation consume the shared workspace quota.
                Limit(f"ws:{slug}", self.settings.rate_workspace_per_hour, 3600),
            ]
        )
        return await self._persist(config, submission, clean, meta)

    def _is_spam(self, submission: LeadSubmission) -> bool:
        if submission.hp_company_website.strip():
            return True
        rendered = submission.form_rendered_at
        if rendered is None or self.settings.min_fill_seconds <= 0:
            return False
        elapsed = (self.clock.now() - rendered).total_seconds()
        return 0 <= elapsed < self.settings.min_fill_seconds

    @staticmethod
    def _check_consent(config: WorkspaceConfig, submission: LeadSubmission) -> None:
        if not submission.consent:
            raise ValidationFailed(
                "Consent is required.",
                errors=[{"loc": ["consent"], "msg": "must be accepted"}],
            )
        if submission.consent_notice_version != config.privacy.version:
            raise ConsentOutdated(
                "The privacy notice has changed. Reload the form and accept the current notice.",
                errors=[
                    {
                        "loc": ["consent_notice_version"],
                        "msg": f"current version is {config.privacy.version}",
                    }
                ],
            )

    async def _persist(
        self,
        config: WorkspaceConfig,
        submission: LeadSubmission,
        clean: dict[str, Any],
        meta: RequestMeta,
    ) -> str:
        slug = config.slug
        now = self.clock.now()
        name_field = _role_field(config, FieldRole.NAME)
        email_field = _role_field(config, FieldRole.EMAIL)
        free_text_field = next(
            (f.id for f in config.form.fields if f.role is FieldRole.FREE_TEXT), None
        )
        country_field = next(
            (f.id for f in config.form.fields if f.type is FieldType.COUNTRY), None
        )
        locale = submission.locale if submission.locale in config.languages.supported else None

        async with self.engine.begin() as conn:
            leads, outbox = LeadRepository(conn), OutboxRepository(conn)
            reference = new_reference(config)
            while await leads.reference_exists(reference):
                reference = new_reference(config)
            lead_id = await leads.insert(
                {
                    "id": uuid.uuid4(),
                    "reference": reference,
                    "workspace_slug": slug,
                    "status": "new",
                    "name": clean[name_field],
                    "email": clean[email_field],
                    "country": clean.get(country_field) if country_field else None,
                    "locale": locale,
                    "answers": clean,
                    "free_text": clean.get(free_text_field) if free_text_field else None,
                    "source": meta.source,
                    "origin": meta.origin,
                    "ip_hash": meta.ip_hash,
                    "user_agent": (meta.user_agent or "")[:USER_AGENT_MAX] or None,
                    "consent_at": now,
                    "consent_notice_version": submission.consent_notice_version,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            await leads.add_event(
                lead_id,
                "submitted",
                payload={"reference": reference, "source": meta.source},
                at=now,
            )
            await outbox.enqueue(
                event_type="lead.created",
                aggregate_id=lead_id,
                lead_id=lead_id,
                payload={"lead": {"id": str(lead_id), "workspace": slug, "reference": reference}},
                idempotency_key=f"lead:{lead_id}:created:1",
                now=now,
            )
        log.info("lead_accepted", lead_id=str(lead_id), workspace=slug, source=meta.source)
        return reference


def _role_field(config: WorkspaceConfig, role: FieldRole) -> str:
    return next(f.id for f in config.form.fields if f.role is role)

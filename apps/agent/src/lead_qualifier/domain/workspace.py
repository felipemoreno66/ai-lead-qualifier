"""Workspace configuration schema (single source of truth for Python and TypeScript).

A workspace is one business: its products, qualification criteria, public form, privacy
notice, tone and CORS origins. Files are validated at startup; see ``workspaces.loader``.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

PLACEHOLDER_MARKER = "TODO(david)"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FIELD_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
LANG_RE = re.compile(r"^[a-z]{2}$")
URL_RE = re.compile(r"^https://[^\s/$.?#][^\s]*$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _url_or_placeholder(value: str) -> str:
    if value.startswith(PLACEHOLDER_MARKER) or URL_RE.match(value):
        return value
    raise ValueError("must be an absolute https:// URL")


def _email_or_placeholder(value: str) -> str:
    if value.startswith(PLACEHOLDER_MARKER) or EMAIL_RE.match(value):
        return value
    raise ValueError("must be an email address")


UrlOrPlaceholder = Annotated[str, AfterValidator(_url_or_placeholder)]
EmailOrPlaceholder = Annotated[str, AfterValidator(_email_or_placeholder)]
LocalizedText = dict[str, str]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldType(StrEnum):
    TEXT = "text"
    EMAIL = "email"
    TEXTAREA = "textarea"
    SELECT = "select"
    COUNTRY = "country"
    NUMBER = "number"
    CHECKBOX = "checkbox"


class FieldRole(StrEnum):
    NAME = "name"
    EMAIL = "email"
    FREE_TEXT = "free_text"


class Tier(StrEnum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class Profile(_Strict):
    name: str = Field(min_length=1, max_length=120)
    tagline: str = Field(min_length=1, max_length=200)
    website: UrlOrPlaceholder
    contact_email: EmailOrPlaceholder
    timezone: str = Field(min_length=1)
    reference_prefix: str | None = Field(default=None, pattern=r"^[A-Z]{2,4}$")
    draft: bool = False


class Languages(_Strict):
    default: str
    supported: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Languages:
        for code in [self.default, *self.supported]:
            if not LANG_RE.match(code):
                raise ValueError(f"language code {code!r} must be two lowercase letters")
        if self.default not in self.supported:
            raise ValueError("default language must be listed in supported")
        if len(set(self.supported)) != len(self.supported):
            raise ValueError("supported languages must be unique")
        return self


class Tone(_Strict):
    style: str
    do: list[str] = []
    dont: list[str] = []
    signature: str


class Price(_Strict):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: int | None = Field(default=None, ge=0)
    note: str | None = None


class Product(_Strict):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=120)
    summary: str
    price: Price | None = None
    duration: str | None = None
    url: UrlOrPlaceholder | None = None


class Criterion(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str
    weight: float = Field(gt=0)
    guide: str | None = None


class Tiers(_Strict):
    hot_min: int = Field(ge=1, le=100)
    warm_min: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def _ordered(self) -> Tiers:
        if self.hot_min <= self.warm_min:
            raise ValueError("hot_min must be greater than warm_min")
        return self


class Qualification(_Strict):
    criteria: list[Criterion] = Field(min_length=1)
    tiers: Tiers

    @field_validator("criteria")
    @classmethod
    def _unique_ids(cls, value: list[Criterion]) -> list[Criterion]:
        _require_unique([c.id for c in value], "criterion id")
        return value


class FieldOption(_Strict):
    value: str = Field(min_length=1, max_length=80)
    label: LocalizedText


class FormField(_Strict):
    id: str
    role: FieldRole | None = None
    type: FieldType
    required: bool = True
    max_length: int | None = Field(default=None, ge=1, le=5000)
    section: LocalizedText | None = None
    label: LocalizedText
    options: list[FieldOption] = []

    @field_validator("id")
    @classmethod
    def _id_format(cls, value: str) -> str:
        if not FIELD_ID_RE.match(value):
            raise ValueError("field id must match ^[a-z][a-z0-9_]{0,39}$")
        return value

    @model_validator(mode="after")
    def _type_rules(self) -> FormField:
        if self.type is FieldType.SELECT:
            if not self.options:
                raise ValueError(f"select field {self.id!r} needs at least one option")
            _require_unique([o.value for o in self.options], f"option value in {self.id!r}")
        elif self.options:
            raise ValueError(f"only select fields may define options (field {self.id!r})")
        if self.role is FieldRole.EMAIL and self.type is not FieldType.EMAIL:
            raise ValueError("the field with role 'email' must have type 'email'")
        if self.role is FieldRole.NAME and self.type is not FieldType.TEXT:
            raise ValueError("the field with role 'name' must have type 'text'")
        if self.role is FieldRole.FREE_TEXT and self.type not in (
            FieldType.TEXT,
            FieldType.TEXTAREA,
        ):
            raise ValueError("the field with role 'free_text' must be text or textarea")
        return self


class Form(_Strict):
    submit_label: LocalizedText
    fields: list[FormField] = Field(min_length=1)

    @field_validator("fields")
    @classmethod
    def _field_rules(cls, value: list[FormField]) -> list[FormField]:
        _require_unique([f.id for f in value], "field id")
        roles = [f.role for f in value if f.role is not None]
        for role in (FieldRole.NAME, FieldRole.EMAIL):
            if roles.count(role) != 1:
                raise ValueError(f"exactly one field with role {role.value!r} is required")
        if roles.count(FieldRole.FREE_TEXT) > 1:
            raise ValueError("at most one field may have role 'free_text'")
        return value


class Privacy(_Strict):
    version: str = Field(min_length=1, max_length=40)
    controller: str
    retention_days: int = Field(gt=0)
    notice: LocalizedText


class Cors(_Strict):
    allowed_origins: list[str] = []


class KnowledgeBase(_Strict):
    path: str = "knowledge-base"
    enabled: bool = True

    @field_validator("path")
    @classmethod
    def _inside_the_workspace(cls, value: str) -> str:
        parts = PurePosixPath(value).parts
        if not value or PurePosixPath(value).is_absolute() or ".." in parts or "\\" in value:
            raise ValueError("knowledge_base.path must be a relative folder inside the workspace")
        return value


class Notifications(_Strict):
    owner_email: EmailOrPlaceholder
    notify_tiers: list[Tier] = [Tier.HOT]


class Drafting(_Strict):
    max_words: int = Field(gt=0, le=1000)
    allowed_link_domains: list[str] = []
    call_to_action: LocalizedText


class EmailChannel(_Strict):
    enabled: bool = True


class WhatsAppChannel(_Strict):
    enabled: bool = False
    provider: str | None = None
    template_name: str | None = None

    @field_validator("enabled")
    @classmethod
    def _not_built_yet(cls, value: bool) -> bool:
        if value:
            raise ValueError("the WhatsApp channel is not implemented yet; keep enabled: false")
        return value


class Channels(_Strict):
    email: EmailChannel = EmailChannel()
    whatsapp: WhatsAppChannel = WhatsAppChannel()


class WorkspaceConfig(_Strict):
    schema_version: Literal[1] = 1
    slug: str
    profile: Profile
    languages: Languages
    tone: Tone
    products: list[Product] = Field(min_length=1)
    qualification: Qualification
    form: Form
    privacy: Privacy
    cors: Cors = Cors()
    knowledge_base: KnowledgeBase = KnowledgeBase()
    notifications: Notifications
    drafting: Drafting
    channels: Channels = Channels()

    @field_validator("slug")
    @classmethod
    def _slug_format(cls, value: str) -> str:
        if not SLUG_RE.match(value):
            raise ValueError("slug must be kebab-case (lowercase letters, digits, hyphens)")
        return value

    @field_validator("products")
    @classmethod
    def _unique_products(cls, value: list[Product]) -> list[Product]:
        _require_unique([p.id for p in value], "product id")
        return value

    @model_validator(mode="after")
    def _localized_texts_cover_languages(self) -> WorkspaceConfig:
        supported = set(self.languages.supported)
        default = self.languages.default
        texts: list[tuple[str, LocalizedText]] = [
            ("form.submit_label", self.form.submit_label),
            ("privacy.notice", self.privacy.notice),
            ("drafting.call_to_action", self.drafting.call_to_action),
        ]
        for f in self.form.fields:
            texts.append((f"form.fields.{f.id}.label", f.label))
            if f.section:
                texts.append((f"form.fields.{f.id}.section", f.section))
            texts.extend(
                (f"form.fields.{f.id}.options.{o.value}.label", o.label) for o in f.options
            )
        problems = []
        for path, text in texts:
            if default not in text:
                problems.append(f"{path}: missing text for default language {default!r}")
            unknown = sorted(set(text) - supported)
            if unknown:
                problems.append(f"{path}: unsupported language(s) {unknown}")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @model_validator(mode="after")
    def _placeholders_only_in_drafts(self) -> WorkspaceConfig:
        if not self.profile.draft:
            found = sorted(set(_find_placeholders(self.model_dump(mode="json"), "")))
            if found:
                raise ValueError(
                    f"{PLACEHOLDER_MARKER} placeholders are only allowed when profile.draft "
                    f"is true (found at: {', '.join(found)})"
                )
        return self

    @property
    def product_ids(self) -> list[str]:
        return [p.id for p in self.products]

    def field(self, field_id: str) -> FormField | None:
        return next((f for f in self.form.fields if f.id == field_id), None)


# --- Public projection (what the browser may see) -----------------------------------------


class PublicFormField(_Strict):
    id: str
    role: FieldRole | None = None
    type: FieldType
    required: bool
    max_length: int | None = None
    section: LocalizedText | None = None
    label: LocalizedText
    options: list[FieldOption] = []


class PublicForm(_Strict):
    submit_label: LocalizedText
    fields: list[PublicFormField]


class PublicPrivacy(_Strict):
    version: str
    controller: str
    retention_days: int
    notice: LocalizedText


class PublicWorkspaceConfig(_Strict):
    slug: str
    name: str
    tagline: str
    default_language: str
    languages: list[str]
    form: PublicForm
    privacy: PublicPrivacy


def to_public(config: WorkspaceConfig) -> PublicWorkspaceConfig:
    return PublicWorkspaceConfig(
        slug=config.slug,
        name=config.profile.name,
        tagline=config.profile.tagline,
        default_language=config.languages.default,
        languages=config.languages.supported,
        form=PublicForm(
            submit_label=config.form.submit_label,
            fields=[
                PublicFormField(
                    id=f.id,
                    role=f.role,
                    type=f.type,
                    required=f.required,
                    max_length=f.max_length,
                    section=f.section,
                    label=f.label,
                    options=f.options,
                )
                for f in config.form.fields
            ],
        ),
        privacy=PublicPrivacy(
            version=config.privacy.version,
            controller=config.privacy.controller,
            retention_days=config.privacy.retention_days,
            notice=config.privacy.notice,
        ),
    )


# --- helpers --------------------------------------------------------------------------------


def _require_unique(values: list[str], what: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {what} {value!r}")
        seen.add(value)


def _find_placeholders(node: Any, path: str) -> list[str]:
    if isinstance(node, str):
        return [path] if PLACEHOLDER_MARKER in node else []
    if isinstance(node, dict):
        return [
            p for k, v in node.items() for p in _find_placeholders(v, f"{path}.{k}".lstrip("."))
        ]
    if isinstance(node, list):
        return [p for i, v in enumerate(node) for p in _find_placeholders(v, f"{path}[{i}]")]
    return []

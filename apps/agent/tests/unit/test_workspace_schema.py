from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from lead_qualifier.domain.workspace import WorkspaceConfig, to_public
from tests.helpers import david_dict, northwind_dict

Mutation = Callable[[dict[str, Any]], None]


def _fields(d: dict[str, Any]) -> list[dict[str, Any]]:
    return d["form"]["fields"]  # type: ignore[no-any-return]


def test_northwind_is_valid_and_not_draft():
    config = WorkspaceConfig.model_validate(northwind_dict())
    assert config.slug == "northwind-academy"
    assert not config.profile.draft
    assert config.product_ids == ["fullstack-bootcamp", "data-ai-course", "mentorship-1on1"]


def test_david_moreno_is_a_valid_draft_with_placeholders():
    config = WorkspaceConfig.model_validate(david_dict())
    assert config.profile.draft


def test_placeholders_are_rejected_outside_drafts():
    data = david_dict()
    data["profile"]["draft"] = False
    with pytest.raises(ValidationError, match=r"TODO\(david\)"):
        WorkspaceConfig.model_validate(data)


def _dup_field(d: dict[str, Any]) -> None:
    _fields(d).append(dict(_fields(d)[2], id="email"))


def _dup_product(d: dict[str, Any]) -> None:
    d["products"].append(dict(d["products"][0]))


def _dup_criterion(d: dict[str, Any]) -> None:
    d["qualification"]["criteria"].append(dict(d["qualification"]["criteria"][0]))


def _zero_weight(d: dict[str, Any]) -> None:
    d["qualification"]["criteria"][0]["weight"] = 0


def _bad_tiers(d: dict[str, Any]) -> None:
    d["qualification"]["tiers"] = {"hot_min": 40, "warm_min": 50}


def _select_without_options(d: dict[str, Any]) -> None:
    next(f for f in _fields(d) if f["id"] == "budget")["options"] = []


def _options_on_text(d: dict[str, Any]) -> None:
    _fields(d)[0]["options"] = [{"value": "x", "label": {"en": "x", "es": "x"}}]


def _two_emails(d: dict[str, Any]) -> None:
    _fields(d)[2].update(role="email", type="email")


def _no_name_role(d: dict[str, Any]) -> None:
    del _fields(d)[0]["role"]


def _two_free_text(d: dict[str, Any]) -> None:
    _fields(d)[4]["role"] = "free_text"


def _bad_field_type(d: dict[str, Any]) -> None:
    _fields(d)[0]["type"] = "color"


def _bad_field_id(d: dict[str, Any]) -> None:
    _fields(d)[0]["id"] = "Full Name"


def _missing_default_language_text(d: dict[str, Any]) -> None:
    del _fields(d)[0]["label"]["en"]


def _unsupported_language_text(d: dict[str, Any]) -> None:
    _fields(d)[0]["label"]["fr"] = "Nom"


def _default_not_supported(d: dict[str, Any]) -> None:
    d["languages"]["default"] = "pt"


def _whatsapp_enabled(d: dict[str, Any]) -> None:
    d["channels"]["whatsapp"]["enabled"] = True


def _bad_slug(d: dict[str, Any]) -> None:
    d["slug"] = "Northwind Academy"


def _unknown_key(d: dict[str, Any]) -> None:
    d["surprise"] = True


def _bad_website(d: dict[str, Any]) -> None:
    d["profile"]["website"] = "http://insecure.example"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (_dup_field, "duplicate field id 'email'"),
        (_dup_product, "duplicate product id"),
        (_dup_criterion, "duplicate criterion id"),
        (_zero_weight, "greater than 0"),
        (_bad_tiers, "hot_min must be greater than warm_min"),
        (_select_without_options, "needs at least one option"),
        (_options_on_text, "only select fields may define options"),
        (_two_emails, "exactly one field with role 'email'"),
        (_no_name_role, "exactly one field with role 'name'"),
        (_two_free_text, "at most one field may have role 'free_text'"),
        (_bad_field_type, "Input should be"),
        (_bad_field_id, "field id must match"),
        (_missing_default_language_text, "missing text for default language"),
        (_unsupported_language_text, "unsupported language"),
        (_default_not_supported, "default language must be listed"),
        (_whatsapp_enabled, "not implemented yet"),
        (_bad_slug, "kebab-case"),
        (_unknown_key, "Extra inputs are not permitted"),
        (_bad_website, "absolute https:// URL"),
    ],
)
def test_invalid_config_is_rejected(mutation: Mutation, message: str):
    data = northwind_dict()
    mutation(data)
    with pytest.raises(ValidationError) as excinfo:
        WorkspaceConfig.model_validate(data)
    assert message in str(excinfo.value)


def test_public_config_hides_internal_settings():
    public = to_public(WorkspaceConfig.model_validate(northwind_dict())).model_dump_json()
    for secret in ("criteria", "owner_email", "weight", "tone", "allowed_origins", "signature"):
        assert secret not in public
    assert "admissions@" not in public

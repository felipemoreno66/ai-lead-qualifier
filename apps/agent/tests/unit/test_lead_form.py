from __future__ import annotations

import json
from pathlib import Path

import pytest

from lead_qualifier.domain.lead_form import validate_answers
from lead_qualifier.domain.workspace import WorkspaceConfig
from tests.helpers import FIXTURES_DIR, northwind_dict

FIELDS = WorkspaceConfig.model_validate(northwind_dict()).form.fields
FIXTURE_FILES = sorted((FIXTURES_DIR / "lead-submissions").glob("*/*.json"))


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_contract_fixture(path: Path):
    case = json.loads(path.read_text())
    _clean, errors = validate_answers(FIELDS, case["fields"])
    assert sorted({e.field for e in errors}) == case["expect"]["error_fields"]
    assert (not errors) == case["expect"]["valid"]


def test_fixtures_exist():
    assert len(FIXTURE_FILES) >= 15


def test_values_are_trimmed_and_email_lowercased():
    case = json.loads((FIXTURES_DIR / "lead-submissions/valid/mixed-case-email.json").read_text())
    clean, errors = validate_answers(FIELDS, case["fields"])
    assert not errors
    assert clean["email"] == "ana.torres@example.com"


def test_optional_blank_field_is_omitted():
    case = json.loads((FIXTURES_DIR / "lead-submissions/valid/empty-optional.json").read_text())
    clean, _ = validate_answers(FIELDS, case["fields"])
    assert "looking_for" not in clean

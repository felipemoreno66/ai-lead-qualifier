from __future__ import annotations

import pytest

from lead_qualifier.domain.draft_guard import guess_language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("How much does the course cost and when does it start for you?", "en"),
        ("¿Cuánto cuesta el curso y hay un plan de pagos para los estudiantes?", "es"),
        ("zxqv wxyz", None),
        ("", None),
    ],
)
def test_guess_language(text: str, expected: str | None):
    assert guess_language(text) == expected

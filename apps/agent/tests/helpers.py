from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACES_DIR = REPO_ROOT / "workspaces"
FIXTURES_DIR = REPO_ROOT / "packages" / "contracts" / "fixtures"


def northwind_dict() -> dict[str, Any]:
    raw = yaml.safe_load((WORKSPACES_DIR / "northwind-academy" / "workspace.yaml").read_text())
    return copy.deepcopy(raw)


def david_dict() -> dict[str, Any]:
    raw = yaml.safe_load((WORKSPACES_DIR / "david-moreno" / "workspace.yaml").read_text())
    return copy.deepcopy(raw)


class FakeClock:
    """A clock tests can move forward."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime.now(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)

from __future__ import annotations

import copy
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

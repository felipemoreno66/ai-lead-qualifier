"""Export JSON Schemas, the OpenAPI document and contract fixtures for the TypeScript side.

Run from ``apps/agent``: ``uv run python -m lead_qualifier.scripts.export_schemas``.
Output goes to ``packages/contracts`` (committed; CI fails when it drifts).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from lead_qualifier.config import Settings
from lead_qualifier.domain.lead_intake import LeadSubmission
from lead_qualifier.domain.workspace import PublicWorkspaceConfig, WorkspaceConfig, to_public
from lead_qualifier.http.app import create_app
from lead_qualifier.http.schemas import (
    AgentRunOut,
    LeadDetail,
    LeadList,
    RetriggerResult,
    ReviewRequest,
    ReviewResult,
    WorkspaceSummary,
)
from lead_qualifier.workspaces.loader import load_workspaces

REPO_ROOT = Path(__file__).resolve().parents[5]
CONTRACTS = REPO_ROOT / "packages" / "contracts"
NORTHWIND = "northwind-academy"


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def main() -> None:
    settings = Settings(
        app_env="test", workspaces_dir=REPO_ROOT / "workspaces", enabled_workspaces=NORTHWIND
    )
    registry = load_workspaces(
        settings.workspaces_dir, app_env="test", enabled=settings.enabled_workspace_slugs
    )
    schemas = CONTRACTS / "schemas"
    _write(schemas / "workspace.schema.json", WorkspaceConfig.model_json_schema())
    _write(schemas / "public-config.schema.json", PublicWorkspaceConfig.model_json_schema())
    _write(schemas / "lead-submission.schema.json", LeadSubmission.model_json_schema())
    _write(schemas / "lead-list.schema.json", LeadList.model_json_schema())
    _write(schemas / "lead-detail.schema.json", LeadDetail.model_json_schema())
    _write(schemas / "retrigger-result.schema.json", RetriggerResult.model_json_schema())
    _write(schemas / "review-request.schema.json", TypeAdapter(ReviewRequest).json_schema())
    _write(schemas / "review-result.schema.json", ReviewResult.model_json_schema())
    _write(schemas / "agent-runs.schema.json", TypeAdapter(list[AgentRunOut]).json_schema())
    _write(
        schemas / "workspace-summaries.schema.json",
        TypeAdapter(list[WorkspaceSummary]).json_schema(),
    )
    _write(CONTRACTS / "openapi.json", create_app(settings, registry=registry).openapi())

    northwind = registry.get(NORTHWIND)
    assert northwind is not None
    _write(
        CONTRACTS / "fixtures" / "northwind-public-config.json",
        to_public(northwind.config).model_dump(mode="json"),
    )
    print(f"Wrote contracts to {CONTRACTS}")


if __name__ == "__main__":
    main()

"""Load and validate workspace folders (``workspaces/<slug>/workspace.yaml``)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from pydantic import ValidationError

from lead_qualifier.domain.workspace import WorkspaceConfig

CONFIG_FILE = "workspace.yaml"
_HINT = " (private instance: create the config with `scripts/private-workspace.sh init`)"
LOCALHOST_RE = re.compile(r"^http://localhost(:\d+)?$")


@dataclass(frozen=True)
class ConfigIssue:
    location: str
    message: str


class WorkspaceConfigError(Exception):
    """Raised with every problem found, so one run shows the whole list."""

    def __init__(self, issues: list[ConfigIssue]) -> None:
        super().__init__(f"{len(issues)} workspace configuration error(s)")
        self.issues = issues

    def __str__(self) -> str:
        return self.render()

    def render(self) -> str:
        lines = [f"Invalid workspace configuration ({len(self.issues)} error(s)):"]
        current = None
        for issue in self.issues:
            if issue.location != current:
                lines.append(f"  {issue.location}")
                current = issue.location
            lines.append(f"    - {issue.message}")
        return "\n".join(lines)


@dataclass(frozen=True)
class LoadedWorkspace:
    config: WorkspaceConfig
    config_hash: str
    path: Path
    enabled: bool

    @property
    def slug(self) -> str:
        return self.config.slug

    @property
    def is_draft(self) -> bool:
        return self.config.profile.draft


class WorkspaceRegistry:
    def __init__(self, workspaces: Iterable[LoadedWorkspace]) -> None:
        self._by_slug = {w.slug: w for w in workspaces}

    def all(self) -> list[LoadedWorkspace]:
        return sorted(self._by_slug.values(), key=lambda w: w.slug)

    def get(self, slug: str) -> LoadedWorkspace | None:
        return self._by_slug.get(slug)

    def public(self, slug: str, *, allow_draft: bool) -> LoadedWorkspace | None:
        """The workspace if its public surface (form + intake) may be served."""
        ws = self._by_slug.get(slug)
        if ws is None or not ws.enabled or (ws.is_draft and not allow_draft):
            return None
        return ws

    def __len__(self) -> int:
        return len(self._by_slug)


def load_workspaces(
    directory: Path,
    *,
    app_env: str,
    enabled: frozenset[str],
) -> WorkspaceRegistry:
    """Load every workspace folder; raise ``WorkspaceConfigError`` listing all problems."""
    issues: list[ConfigIssue] = []
    loaded: list[LoadedWorkspace] = []

    if not directory.is_dir():
        raise WorkspaceConfigError(
            [ConfigIssue(str(directory), "workspaces directory does not exist" + _HINT)]
        )

    for folder in sorted(p for p in directory.iterdir() if p.is_dir()):
        if folder.name.startswith(("_", ".")):
            continue
        workspace, folder_issues = _load_one(
            folder, app_env=app_env, is_enabled=folder.name in enabled
        )
        issues.extend(folder_issues)
        if workspace:
            loaded.append(workspace)

    known = {w.slug for w in loaded} | {p.name for p in directory.iterdir() if p.is_dir()}
    for slug in sorted(enabled - known):
        issues.append(
            ConfigIssue(
                "ENABLED_WORKSPACES", f"workspace {slug!r} has no folder in {directory}" + _HINT
            )
        )
    if issues:
        raise WorkspaceConfigError(issues)
    return WorkspaceRegistry(loaded)


def _load_one(
    folder: Path, *, app_env: str, is_enabled: bool
) -> tuple[LoadedWorkspace | None, list[ConfigIssue]]:
    file = folder / CONFIG_FILE
    where = f"{folder.name}/{CONFIG_FILE}"
    if not file.is_file():
        return None, [ConfigIssue(where, "file not found")]
    try:
        raw: Any = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = f" (line {mark.line + 1})" if mark else ""
        return None, [ConfigIssue(where, f"invalid YAML{line}: {getattr(exc, 'problem', exc)}")]
    if not isinstance(raw, dict):
        return None, [ConfigIssue(where, "the file must contain a YAML mapping at the top level")]

    try:
        config = WorkspaceConfig.model_validate(raw)
    except ValidationError as exc:
        return None, [
            ConfigIssue(where, f"{_loc(err['loc'])}: {err['msg'].removeprefix('Value error, ')}")
            for err in exc.errors()
        ]

    issues: list[ConfigIssue] = []
    if config.slug != folder.name:
        issues.append(ConfigIssue(where, f"slug {config.slug!r} must match the folder name"))
    for origin in config.cors.allowed_origins:
        problem = _origin_problem(origin, app_env)
        if problem:
            issues.append(ConfigIssue(where, f"cors.allowed_origins: {origin!r} {problem}"))
    kb = config.knowledge_base
    if kb.enabled and not (folder / kb.path).is_dir():
        issues.append(ConfigIssue(where, f"knowledge_base.path: folder {kb.path!r} does not exist"))
    if issues:
        return None, issues

    canonical = json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return LoadedWorkspace(config, digest, folder, is_enabled), []


def _origin_problem(origin: str, app_env: str) -> str | None:
    if origin.startswith("https://"):
        parts = urlsplit(origin)
        if parts.hostname and not parts.path.strip("/") and not parts.query and not parts.fragment:
            return None
        return "must be a bare origin (scheme and host, no path)"
    if LOCALHOST_RE.match(origin):
        return None if app_env == "local" else "http://localhost is only allowed when APP_ENV=local"
    return "must be an absolute https:// origin"


def _loc(loc: tuple[int | str, ...]) -> str:
    return ".".join(str(p) for p in loc) or "(root)"

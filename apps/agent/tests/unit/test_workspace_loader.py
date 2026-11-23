from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from lead_qualifier.workspaces.loader import WorkspaceConfigError, load_workspaces
from tests.helpers import WORKSPACES_DIR, northwind_dict


def _copy_northwind(tmp_path: Path, slug: str = "northwind-academy") -> Path:
    target = tmp_path / slug
    shutil.copytree(WORKSPACES_DIR / "northwind-academy", target)
    return target


def _write(folder: Path, data: dict) -> None:
    (folder / "workspace.yaml").write_text(yaml.safe_dump(data, allow_unicode=True))


def _load(tmp_path: Path, enabled: str = "northwind-academy", app_env: str = "test"):
    return load_workspaces(tmp_path, app_env=app_env, enabled=frozenset(enabled.split(",")))


def test_loads_the_repo_workspaces():
    registry = load_workspaces(
        WORKSPACES_DIR, app_env="test", enabled=frozenset({"northwind-academy"})
    )
    assert [w.slug for w in registry.all()] == ["david-moreno", "northwind-academy"]
    assert registry.public("northwind-academy", allow_draft=False) is not None


def test_draft_and_disabled_workspaces_are_not_public():
    registry = load_workspaces(
        WORKSPACES_DIR, app_env="test", enabled=frozenset({"northwind-academy", "david-moreno"})
    )
    assert registry.public("david-moreno", allow_draft=False) is None
    assert registry.public("david-moreno", allow_draft=True) is not None
    only_nw = load_workspaces(
        WORKSPACES_DIR, app_env="test", enabled=frozenset({"northwind-academy"})
    )
    assert only_nw.public("david-moreno", allow_draft=True) is None


def test_config_hash_changes_with_content(tmp_path: Path):
    folder = _copy_northwind(tmp_path)
    first = _load(tmp_path).get("northwind-academy")
    data = northwind_dict()
    data["profile"]["tagline"] = "Another tagline"
    _write(folder, data)
    second = _load(tmp_path).get("northwind-academy")
    assert first and second and first.config_hash != second.config_hash


def test_schema_errors_are_reported_with_the_file_name(tmp_path: Path):
    folder = _copy_northwind(tmp_path)
    data = northwind_dict()
    data["form"]["fields"].append(dict(data["form"]["fields"][2], id="email"))
    data["cors"]["allowed_origins"] = ["ftp://nope.example", "https://ok.example/path"]
    _write(folder, data)
    with pytest.raises(WorkspaceConfigError) as excinfo:
        _load(tmp_path)
    text = excinfo.value.render()
    assert "northwind-academy/workspace.yaml" in text
    assert "duplicate field id 'email'" in text


def test_bad_origins_are_reported_with_the_origin(tmp_path: Path):
    folder = _copy_northwind(tmp_path)
    data = northwind_dict()
    data["cors"]["allowed_origins"] = ["ftp://nope.example", "https://ok.example/path"]
    _write(folder, data)
    with pytest.raises(WorkspaceConfigError) as excinfo:
        _load(tmp_path)
    text = excinfo.value.render()
    assert "'ftp://nope.example' must be an absolute https:// origin" in text
    assert "'https://ok.example/path' must be a bare origin" in text


def test_localhost_origin_only_in_local_env(tmp_path: Path):
    folder = _copy_northwind(tmp_path)
    data = northwind_dict()
    data["cors"]["allowed_origins"] = ["http://localhost:3000"]
    _write(folder, data)
    assert _load(tmp_path, app_env="local").get("northwind-academy")
    with pytest.raises(WorkspaceConfigError, match="only allowed when APP_ENV=local"):
        _load(tmp_path, app_env="production")


def test_slug_must_match_folder(tmp_path: Path):
    _copy_northwind(tmp_path, slug="other-name")
    with pytest.raises(WorkspaceConfigError, match="must match the folder name"):
        _load(tmp_path, enabled="other-name")


def test_missing_knowledge_base_folder(tmp_path: Path):
    folder = _copy_northwind(tmp_path)
    shutil.rmtree(folder / "knowledge-base")
    with pytest.raises(WorkspaceConfigError, match=r"knowledge_base\.path"):
        _load(tmp_path)


def test_yaml_syntax_error_mentions_the_line(tmp_path: Path):
    folder = _copy_northwind(tmp_path)
    (folder / "workspace.yaml").write_text("slug: [unclosed\nprofile: x\n")
    with pytest.raises(WorkspaceConfigError, match="invalid YAML"):
        _load(tmp_path)


def test_enabled_slug_without_folder_is_an_error(tmp_path: Path):
    _copy_northwind(tmp_path)
    with pytest.raises(WorkspaceConfigError, match="no-such-business"):
        _load(tmp_path, enabled="northwind-academy,no-such-business")


def test_folders_starting_with_underscore_are_ignored(tmp_path: Path):
    _copy_northwind(tmp_path)
    (tmp_path / "_fixture").mkdir()
    assert len(_load(tmp_path)) == 1


def test_invalid_config_makes_the_service_exit_with_a_readable_list(tmp_path: Path):
    import os
    import subprocess
    import sys

    folder = _copy_northwind(tmp_path)
    data = northwind_dict()
    data["form"]["fields"].append(dict(data["form"]["fields"][2], id="email"))
    data["cors"]["allowed_origins"] = ["ftp://nope.example"]
    _write(folder, data)
    env = {**os.environ, "APP_ENV": "test", "WORKSPACES_DIR": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-c", "import lead_qualifier.entrypoint"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Invalid workspace configuration (1 error(s))" in result.stderr
    assert "duplicate field id 'email'" in result.stderr
    assert "Traceback" not in result.stderr

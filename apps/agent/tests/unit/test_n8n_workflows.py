from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from lead_qualifier.infrastructure.outbox.publishers import WEBHOOK_PATHS
from tests.helpers import REPO_ROOT

WORKFLOWS = REPO_ROOT / "n8n" / "workflows"
spec = importlib.util.spec_from_file_location(
    "sanitize_n8n", REPO_ROOT / "scripts" / "sanitize_n8n.py"
)
assert spec and spec.loader
sanitize_n8n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sanitize_n8n)


def test_committed_workflows_have_no_credentials_or_execution_data():
    assert sanitize_n8n.main(["--check", str(WORKFLOWS)]) == 0


def test_check_detects_credentials_and_pin_data(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    bad = {
        "name": "x",
        "pinData": {"node": [{"json": {"email": "a@b.c"}}]},
        "nodes": [{"name": "Mail", "credentials": {"smtp": {"id": "1", "name": "n"}}}],
    }
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    assert sanitize_n8n.main(["--check", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "pinData" in err and "has credentials" in err
    assert sanitize_n8n.main([str(tmp_path)]) == 0  # rewrite
    assert sanitize_n8n.main(["--check", str(tmp_path)]) == 0


def test_every_published_event_type_has_a_workflow_with_the_same_webhook_path():
    paths = {
        node["parameters"]["path"]
        for file in WORKFLOWS.glob("*.json")
        for node in json.loads(file.read_text())["nodes"]
        if node["type"] == "n8n-nodes-base.webhook"
    }
    assert paths >= {WEBHOOK_PATHS["lead.created"]}


def test_lead_created_workflow_verifies_signature_before_anything_else():
    workflow = json.loads((WORKFLOWS / "lead-created.json").read_text())
    order = [n["name"] for n in workflow["nodes"]]
    assert order[:2] == ["Lead created webhook", "Verify signature"]
    assert (
        workflow["connections"]["Lead created webhook"]["main"][0][0]["node"] == "Verify signature"
    )
    code = next(n for n in workflow["nodes"] if n["name"] == "Verify signature")
    assert "timingSafeEqual" in code["parameters"]["jsCode"]

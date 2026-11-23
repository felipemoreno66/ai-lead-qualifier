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
    assert ".POST /webhook/lead-created." in code["parameters"]["jsCode"]


def _workflow(name: str) -> dict:  # type: ignore[type-arg]
    return json.loads((WORKFLOWS / f"{name}.json").read_text())


def _node(workflow: dict, name: str) -> dict:  # type: ignore[type-arg]
    return next(n for n in workflow["nodes"] if n["name"] == name)


@pytest.mark.parametrize("name", ["lead-created", "message-approved"])
def test_workflow_graphs_are_consistent(name: str):
    workflow = _workflow(name)
    names = [n["name"] for n in workflow["nodes"]]
    assert len(names) == len(set(names)) and len({n["id"] for n in workflow["nodes"]}) == len(names)
    for source, outputs in workflow["connections"].items():
        assert source in names
        for group in outputs["main"]:
            assert all(link["node"] in names for link in group)


def test_message_approved_has_its_own_signed_webhook_and_an_email_only_branch():
    workflow = _workflow("message-approved")
    order = [n["name"] for n in workflow["nodes"]]
    assert order[:2] == ["Message approved webhook", "Verify signature"]
    assert _node(workflow, order[0])["parameters"]["path"] == WEBHOOK_PATHS["message.approved"]
    verify = _node(workflow, "Verify signature")["parameters"]["jsCode"]
    assert "timingSafeEqual" in verify and ".POST /webhook/message-approved." in verify
    channel = _node(workflow, "Channel is email?")["parameters"]["conditions"]["conditions"][0]
    assert channel["leftValue"] == "={{ $json.channel }}" and channel["rightValue"] == "email"
    # the non-email branch and a failing SMTP send both report a failure; success reports sent
    assert (
        workflow["connections"]["Channel is email?"]["main"][1][0]["node"] == "Sign failed callback"
    )
    send = _node(workflow, "Send email")
    assert send["onError"] == "continueErrorOutput"
    assert workflow["connections"]["Send email"]["main"][0][0]["node"] == "Sign sent callback"
    assert workflow["connections"]["Send email"]["main"][1][0]["node"] == "Sign failed callback"
    assert "credentials" not in send


def test_lead_created_qualifies_first_and_notifies_only_hot_leads_without_personal_data():
    workflow = _workflow("lead-created")
    qualify = _node(workflow, "Qualify lead")["parameters"]
    assert qualify["url"].endswith("/internal/leads/{{ $json.lead.id }}/qualify")
    assert qualify["options"]["response"]["response"]["neverError"] is True
    hot = _node(workflow, "Hot lead?")["parameters"]["conditions"]["conditions"][0]
    assert hot["leftValue"] == "={{ $json.tier }}" and hot["rightValue"] == "hot"
    connections = workflow["connections"]
    assert connections["Hot lead?"]["main"][0][0]["node"] == "Notify owner"
    assert connections["Hot lead?"]["main"][1][0]["node"] == "Acknowledge event"
    notify = _node(workflow, "Notify owner")["parameters"]
    text = notify["subject"] + notify["text"]
    assert "reference" in text and "/dashboard/leads/" in text
    for personal in ("email", "name", "answers", "free_text", "country"):
        assert f"json.{personal}" not in text and f"lead.{personal}" not in text


def test_the_callback_signature_computed_in_n8n_is_accepted_by_the_agent(tmp_path: Path):
    """Runs the workflow's own Code node under Node and checks the HMAC the agent verifies."""
    import shutil
    import subprocess

    from lead_qualifier.infrastructure.outbox.publishers import sign

    node_bin = shutil.which("node")
    if node_bin is None:
        pytest.skip("node is not installed")
    workflow = _workflow("message-approved")
    for name, expected_path, input_json in (
        ("Sign sent callback", "/sent", '{"messageId": "<abc@smtp>"}'),
        ("Sign failed callback", "/send-failed", "{}"),
    ):
        code = _node(workflow, name)["parameters"]["jsCode"]
        harness = (
            "process.env.N8N_WEBHOOK_SECRET='s3cret-for-the-test'; process.env.AGENT_INTERNAL_URL='http://agent:8000';\n"
            "const $env = process.env;\n"
            "const $ = () => ({ first: () => ({ json: { message: { id: 'm-1' } } }) });\n"
            f"const $input = {{ first: () => ({{ json: {input_json} }}) }};\n"
            f"(async () => {{ {code} }})().then(r => console.log(JSON.stringify(r[0].json)));"
        )
        script = tmp_path / "run.js"
        script.write_text(harness)
        out = json.loads(
            subprocess.run(  # noqa: S603 - our own harness script
                [node_bin, str(script)], capture_output=True, text=True, check=True
            ).stdout
        )
        assert out["url"] == f"http://agent:8000/internal/messages/m-1{expected_path}"
        assert out["signature"] == sign(
            out["body"].encode(),
            "s3cret-for-the-test",
            out["timestamp"],
            method="POST",
            path=f"/internal/messages/m-1{expected_path}",
        )
        assert json.loads(out["body"])["message_id"] == "m-1"

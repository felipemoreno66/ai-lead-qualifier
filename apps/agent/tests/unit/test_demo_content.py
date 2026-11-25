"""The demo fixtures must stay valid against the schema enums and agree with the seeded leads."""

from __future__ import annotations

import json

from lead_qualifier.infrastructure.db.tables import (
    AGENT_RUN_STATUSES,
    LEAD_STATUSES,
    MESSAGE_STATUSES,
)
from lead_qualifier.scripts.demo_init import load_content
from lead_qualifier.scripts.seed import DEFAULT_SEED_FILE, PATHS

# A message's status is only valid next to these lead statuses.
LEAD_FOR_MESSAGE = {"draft": "pending_review", "sent": "sent", "rejected": "rejected"}


def test_every_demo_item_belongs_to_a_seeded_lead_in_a_matching_state():
    leads = {e["reference"]: e for e in json.loads(DEFAULT_SEED_FILE.read_text())["leads"]}
    content = load_content()["leads"]
    assert content, "no demo content"
    for reference, item in content.items():
        lead = leads[reference]
        assert lead["status"] in LEAD_STATUSES and lead["status"] in PATHS
        message = item.get("message")
        if message:
            assert message["status"] in MESSAGE_STATUSES
            assert LEAD_FOR_MESSAGE[message["status"]] == lead["status"], reference
            assert message["language"] in {"en", "es", "pt"}
            assert message["subject"] and message["body"]
            if message.get("edited"):
                assert message["original_body"]
        else:
            assert item.get("failed") and lead["status"] == "error", reference
        assert item["calls"], reference


def test_the_run_statuses_the_loader_writes_are_valid_enums():
    assert {"failed", "interrupted", "completed"} <= set(AGENT_RUN_STATUSES)

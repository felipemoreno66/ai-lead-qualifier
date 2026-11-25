from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from lead_qualifier.agent.graph import GraphDeps, run_qualification
from lead_qualifier.agent.models import LeadInput
from lead_qualifier.domain.workspace import WorkspaceConfig
from lead_qualifier.infrastructure.llm.fake import FakeProvider
from lead_qualifier.infrastructure.llm.fake_handlers import FAKE_HANDLERS
from tests.helpers import WORKSPACES_DIR

SEEDS = json.loads((WORKSPACES_DIR.parent / "db/seeds/northwind_leads.json").read_text())["leads"]


def lead_from_seed(entry: dict[str, Any]) -> LeadInput:
    return LeadInput(
        name=entry["name"],
        email=entry["email"],
        country=entry.get("country"),
        locale=entry.get("locale"),
        answers=entry["answers"],
        free_text=entry.get("free_text"),
    )


def make_lead(**answers: Any) -> LeadInput:
    base = {
        "name": "ana perez",
        "email": "ana@example.com",
        "program": "data-ai-course",
        "career_goal": "I want to become a data analyst and learn Python and SQL.",
        "budget": "2500-5000",
        "availability": "10-20h",
        "country": "CO",
    }
    base.update(answers)
    return LeadInput(
        name=base["name"],
        email=base["email"],
        country=base["country"],
        locale="en",
        answers=base,
        free_text=base.get("looking_for"),
    )


def deps(workspace: WorkspaceConfig, provider: FakeProvider | None = None) -> GraphDeps:
    return GraphDeps(
        provider=provider or FakeProvider(handlers=FAKE_HANDLERS),
        workspace=workspace,
        agent_run_id=uuid4(),
        model_for=lambda _task: "claude-haiku-5-5",
    )


async def run(
    lead: LeadInput, workspace: WorkspaceConfig, provider: FakeProvider | None = None
) -> dict[str, Any]:
    return await run_qualification(
        lead, deps(workspace, provider), checkpointer=InMemorySaver(), thread_id=str(uuid4())
    )

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from lead_qualifier.ports.llm import ChatMessage, StructuredRequest


class Verdict(BaseModel):
    score: int = Field(ge=0, le=100)
    tier: Literal["hot", "warm", "cold"]
    reasons: list[str] = Field(min_length=1)


def verdict_request(
    text: str = "Maria wants the data course", **kw: object
) -> StructuredRequest[Verdict]:
    return StructuredRequest(
        task="qualify",
        system="You qualify leads.",
        messages=[ChatMessage("user", text)],
        output_model=Verdict,
        model="claude-haiku-5-5",
        max_tokens=512,
        **kw,  # type: ignore[arg-type]
    )

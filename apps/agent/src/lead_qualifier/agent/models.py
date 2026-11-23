"""Typed inputs and outputs of the qualification graph."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lead_qualifier.domain.scoring import Judgment
from lead_qualifier.domain.workspace import Tier


class LeadInput(BaseModel):
    """The lead fields the agent may see. Everything here is untrusted prospect data."""

    name: str
    email: str
    country: str | None = None
    locale: str | None = None
    answers: dict[str, Any] = Field(default_factory=dict)
    free_text: str | None = None


class LeadProfile(BaseModel):
    """Output of ``extract``: a normalised view of the submission."""

    model_config = ConfigDict(extra="forbid")

    normalized_name: str = Field(max_length=120)
    detected_language: str = Field(pattern=r"^[a-z]{2}$")
    goal_summary: str = Field(max_length=300)
    questions: list[str] = Field(default_factory=list, max_length=5)
    injection_suspected: bool = False

    @property
    def has_questions(self) -> bool:
        return bool(self.questions)


class CriterionJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    judgment: Judgment
    evidence: str = Field(max_length=300)


class QualificationOutput(BaseModel):
    """Output of ``qualify`` as produced by the model: judgments, never a score."""

    model_config = ConfigDict(extra="forbid")

    criteria: list[CriterionJudgment] = Field(min_length=1)
    recommended_product: str
    reasons: list[str] = Field(min_length=1, max_length=5)


class QualificationResult(BaseModel):
    """What gets stored on the lead once the score has been computed in code."""

    score: int = Field(ge=0, le=100)
    tier: Tier
    recommended_product: str
    criteria: list[CriterionJudgment]
    reasons: list[str]
    profile: LeadProfile
    tier_capped: bool = False

"""Builds the configured provider and resolves the model per task."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncEngine

from lead_qualifier.config import Settings
from lead_qualifier.infrastructure.llm.anthropic_provider import AnthropicProvider
from lead_qualifier.infrastructure.llm.bedrock_provider import BedrockProvider
from lead_qualifier.infrastructure.llm.fake import FakeProvider
from lead_qualifier.infrastructure.llm.fake_handlers import FAKE_HANDLERS
from lead_qualifier.infrastructure.llm.openai_provider import OpenAIProvider
from lead_qualifier.infrastructure.llm.pricing import PricingTable
from lead_qualifier.infrastructure.llm.recording import RecordingProvider
from lead_qualifier.ports.llm import LLMProvider


def model_for(settings: Settings, task: str) -> str:
    """``LLM_MODEL_DRAFT`` (when set) for drafting, ``LLM_MODEL_DEFAULT`` for everything else."""
    if task == "draft" and settings.llm_model_draft:
        return settings.llm_model_draft
    return settings.llm_model_default


def _adapter(settings: Settings) -> LLMProvider:
    match settings.llm_provider:
        case "fake":
            return FakeProvider(handlers=FAKE_HANDLERS)
        case "anthropic":
            key = settings.anthropic_api_key.get_secret_value()
            if not key:
                raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
            return AnthropicProvider(api_key=key)
        case "bedrock":
            if not settings.aws_region:
                raise ValueError("AWS_REGION is required when LLM_PROVIDER=bedrock")
            return BedrockProvider(aws_region=settings.aws_region)
        case "openai":
            if not settings.openai_api_key.get_secret_value():
                raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
            return OpenAIProvider(api_key=settings.openai_api_key)


def build_provider(settings: Settings, engine: AsyncEngine) -> LLMProvider:
    """The adapter selected by ``LLM_PROVIDER`` wrapped in the recording/budget decorator."""
    pricing = PricingTable.load()
    if settings.llm_provider != "fake":
        for model in {settings.llm_model_default, settings.llm_model_draft} - {""}:
            if not pricing.knows(model):
                raise ValueError(
                    f"model {model!r} is not in pricing.yaml; add its prices before using it "
                    "so the budget guard can count its cost"
                )
    return RecordingProvider(
        _adapter(settings),
        engine,
        pricing,
        budget_usd=Decimal(str(settings.llm_budget_usd)),
        max_calls_per_run=settings.llm_max_calls_per_lead,
    )

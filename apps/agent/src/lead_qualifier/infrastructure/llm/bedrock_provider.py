"""Amazon Bedrock adapter (optional, documented, not exercised in CI).

Bedrock serves Claude through the same Messages API, so this reuses ``AnthropicProvider`` with the
SDK's ``AsyncAnthropicBedrockMantle`` client. Model ids carry the ``anthropic.`` prefix, e.g.
``anthropic.claude-haiku-5-5`` (set ``LLM_MODEL_DEFAULT`` accordingly). Credentials come from the
standard AWS chain (env vars, profile or role); the region from ``AWS_REGION``.
"""

from __future__ import annotations

from anthropic import AsyncAnthropicBedrockMantle

from lead_qualifier.infrastructure.llm.anthropic_provider import AnthropicProvider


class BedrockProvider(AnthropicProvider):
    name = "bedrock"

    def __init__(self, *, aws_region: str) -> None:
        super().__init__(client=AsyncAnthropicBedrockMantle(aws_region=aws_region))  # type: ignore[arg-type]

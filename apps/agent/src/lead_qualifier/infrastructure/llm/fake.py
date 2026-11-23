"""Deterministic fake provider: no network, no randomness beyond a seed derived from the input.

Without a registered handler it synthesises a valid instance of the requested pydantic model from
its JSON schema. Task-specific rule-based handlers (extract, qualify, draft) are registered by the
agent graph (M2.2). ``script`` injects failures on chosen calls (repair loop, error paths).
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from lead_qualifier.ports.llm import (
    ChatMessage,
    LLMResult,
    StructuredRequest,
    TextRequest,
    Usage,
)

# One scripted step per call, in order: None = default behaviour, str = raw text to return,
# dict = JSON payload to return, BaseException = raise it.
ScriptStep = None | str | dict[str, Any] | BaseException
Handler = Callable[[StructuredRequest[Any]], dict[str, Any]]

PROVIDER_NAME = "fake"


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def seed_for(task: str, payload: object) -> int:
    digest = hashlib.sha256((task + canonical_json(payload)).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _messages_payload(system: str, messages: Sequence[ChatMessage]) -> dict[str, object]:
    return {"system": system, "messages": [[m.role, m.content] for m in messages]}


class _SchemaSynth:
    """Builds a schema-valid value deterministically from a JSON schema and a seeded RNG."""

    def __init__(self, schema: dict[str, Any], rng: random.Random) -> None:
        self._defs: dict[str, Any] = schema.get("$defs", {})
        self._rng = rng

    def build(self, node: dict[str, Any], hint: str = "value") -> Any:
        if "$ref" in node:
            return self.build(self._defs[node["$ref"].rsplit("/", 1)[-1]], hint)
        if "const" in node:
            return node["const"]
        if "enum" in node:
            return self._rng.choice(node["enum"])
        for key in ("anyOf", "oneOf"):
            if key in node:
                options = [o for o in node[key] if o.get("type") != "null"] or node[key]
                return self.build(options[0], hint)
        kind = node.get("type")
        if kind == "object" or "properties" in node:
            props: dict[str, Any] = node.get("properties", {})
            return {name: self.build(sub, name) for name, sub in props.items()}
        if kind == "array":
            count = max(int(node.get("minItems", 1)), 1)
            return [self.build(node.get("items", {}), hint) for _ in range(count)]
        if kind == "integer":
            return self._rng.randint(int(node.get("minimum", 0)), int(node.get("maximum", 100)))
        if kind == "number":
            return round(self._rng.uniform(node.get("minimum", 0), node.get("maximum", 100)), 2)
        if kind == "boolean":
            return self._rng.random() < 0.5
        text = f"fake-{hint}-{self._rng.randrange(16**4):04x}"
        return text[: int(node["maxLength"])] if "maxLength" in node else text


class FakeProvider:
    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        script: Sequence[ScriptStep] = (),
        handlers: Mapping[str, Handler] | None = None,
    ) -> None:
        self._script = list(script)
        self._handlers = dict(handlers or {})
        self.calls = 0

    def _next_step(self) -> ScriptStep:
        step = self._script[self.calls] if self.calls < len(self._script) else None
        self.calls += 1
        return step

    async def generate_structured[T: BaseModel](self, req: StructuredRequest[T]) -> LLMResult[T]:
        from lead_qualifier.infrastructure.llm.structured import parse_output

        step = self._next_step()
        if isinstance(step, BaseException):
            raise step
        payload = _messages_payload(req.system, req.messages)
        if isinstance(step, str):
            raw = step
        elif isinstance(step, dict):
            raw = canonical_json(step)
        else:
            handler = self._handlers.get(req.task)
            if handler is not None:
                data = handler(req)
            else:
                seed = seed_for(req.task, [payload, req.output_model.__name__])
                rng = random.Random(seed)  # noqa: S311 - deterministic, not security
                schema = req.output_model.model_json_schema()
                data = _SchemaSynth(schema, rng).build(schema)
            raw = canonical_json(data)
        usage = Usage(input_tokens=_tokens(canonical_json(payload)), output_tokens=_tokens(raw))
        value = parse_output(
            raw,
            req.output_model,
            usage=usage,
            latency_ms=0,
            provider=self.name,
            model_id=req.model,
        )
        return LLMResult(value, raw, usage, 0, self.name, req.model)

    async def generate_text(self, req: TextRequest) -> LLMResult[str]:
        step = self._next_step()
        if isinstance(step, BaseException):
            raise step
        payload = _messages_payload(req.system, req.messages)
        if isinstance(step, str):
            text = step
        else:
            text = f"fake-{req.task}-{seed_for(req.task, payload) % 16**6:06x}"
        usage = Usage(input_tokens=_tokens(canonical_json(payload)), output_tokens=_tokens(text))
        return LLMResult(text, text, usage, 0, self.name, req.model)

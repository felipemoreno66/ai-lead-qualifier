"""Minimal Docker Compose reader for tests: no Docker needed.

Handles what the demo files use: YAML anchors and merge keys, the ``!reset`` / ``!override`` tags,
``${VAR}``, ``${VAR:-default}`` and ``${VAR:?message}`` interpolation (nested defaults included) and
per-key merging of ``environment`` between files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


class Reset:
    pass


class _Loader(yaml.SafeLoader):
    pass


def _reset(loader: yaml.SafeLoader, node: yaml.Node) -> Reset:
    return Reset()


def _override(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)  # type: ignore[arg-type]


_Loader.add_constructor("!reset", _reset)
_Loader.add_constructor("!override", _override)


class MissingVariable(Exception):
    pass


def interpolate(value: str, env: dict[str, str]) -> str:
    def expand(text: str) -> str:
        out, i = [], 0
        while i < len(text):
            if text.startswith("${", i):
                depth, j = 1, i + 2
                while depth:
                    depth += {"{": 1, "}": -1}.get(text[j], 0)
                    j += 1
                out.append(resolve(text[i + 2 : j - 1]))
                i = j
            else:
                out.append(text[i])
                i += 1
        return "".join(out)

    def resolve(body: str) -> str:
        match = re.match(r"(\w+)(:-|:\?|-|\?)?(.*)$", body, re.S)
        assert match, body
        name, op, rest = match.groups()
        current = env.get(name, "")
        if op == ":?" and not current:
            raise MissingVariable(f"{name}: {rest}")
        if op in (":-", "-"):
            return current or expand(rest)
        return current

    return expand(value)


def _walk(node: Any, env: dict[str, str]) -> Any:
    if isinstance(node, str):
        return interpolate(node, env)
    if isinstance(node, list):
        return [_walk(item, env) for item in node]
    if isinstance(node, dict):
        return {k: _walk(v, env) for k, v in node.items()}
    return node


def load_merged(root: Path, files: list[str], env: dict[str, str]) -> dict[str, Any]:
    """Merge the files like ``docker compose -f a -f b`` (services only) and interpolate."""
    services: dict[str, dict[str, Any]] = {}
    for name in files:
        data = yaml.load((root / name).read_text(encoding="utf-8"), Loader=_Loader)  # noqa: S506
        for svc, spec in (data.get("services") or {}).items():
            target = services.setdefault(svc, {})
            for key, val in spec.items():
                if isinstance(val, Reset):
                    target.pop(key, None)
                elif key == "environment" and isinstance(target.get(key), dict):
                    target[key] = {**target[key], **val}
                else:
                    target[key] = val
    return _walk(services, env)  # type: ignore[no-any-return]


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            values[name.strip()] = value.strip()
    return values

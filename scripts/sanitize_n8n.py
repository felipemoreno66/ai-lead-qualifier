#!/usr/bin/env python3
"""Keep exported n8n workflows free of credentials and execution data.

    python scripts/sanitize_n8n.py n8n/workflows            # rewrite files in place
    python scripts/sanitize_n8n.py --check n8n/workflows    # fail (exit 1) if anything to strip

Workflows reference no credentials in the repository: `n8n/prepare.js` attaches the local
Mailpit credential at container start.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

STRIP_TOP_LEVEL = ("pinData", "staticData", "credentials", "shared", "tags", "versionId", "meta")


def find_problems(workflow: dict[str, Any]) -> list[str]:
    problems = [f"top-level '{key}'" for key in STRIP_TOP_LEVEL if key in workflow]
    problems += [
        f"node '{node.get('name', '?')}' has credentials"
        for node in workflow.get("nodes", [])
        if "credentials" in node
    ]
    return problems


def sanitize(workflow: dict[str, Any]) -> dict[str, Any]:
    clean = {k: v for k, v in workflow.items() if k not in STRIP_TOP_LEVEL}
    clean["nodes"] = [{k: v for k, v in n.items() if k != "credentials"} for n in workflow["nodes"]]
    return clean


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    files = sorted(args.directory.glob("*.json"))
    if not files:
        print(f"no workflow files in {args.directory}", file=sys.stderr)
        return 1
    failed = False
    for file in files:
        workflow = json.loads(file.read_text(encoding="utf-8"))
        problems = find_problems(workflow)
        if args.check:
            for problem in problems:
                print(f"{file}: {problem}", file=sys.stderr)
            failed = failed or bool(problems)
        elif problems:
            file.write_text(json.dumps(sanitize(workflow), indent=2) + "\n", encoding="utf-8")
            print(f"sanitized {file}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

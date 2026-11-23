"""ASGI entrypoint for uvicorn: `uvicorn lead_qualifier.entrypoint:app`.

Configuration errors (for example an invalid workspace file) are printed as a readable
list and the process exits with status 1 instead of dumping a stack trace.
"""

from __future__ import annotations

import sys

from fastapi import FastAPI

from lead_qualifier.http.app import create_app
from lead_qualifier.workspaces.loader import WorkspaceConfigError


def _build() -> FastAPI:
    try:
        return create_app()
    except WorkspaceConfigError as exc:
        print(exc.render(), file=sys.stderr)
        raise SystemExit(1) from None


app = _build()

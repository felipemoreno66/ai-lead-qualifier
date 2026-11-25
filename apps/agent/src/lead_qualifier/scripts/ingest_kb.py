"""Ingest a workspace's knowledge base into pgvector.

    python -m lead_qualifier.scripts.ingest_kb <workspace> [--force]
    python -m lead_qualifier.scripts.ingest_kb --warm   # pre-download the model

Unchanged documents are skipped (content hash), deleted ones are removed. With the default
fastembed provider the model is downloaded into ``EMBEDDINGS_CACHE_DIR`` on first use.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from lead_qualifier.config import Settings, get_settings
from lead_qualifier.infrastructure.db.engine import create_engine
from lead_qualifier.infrastructure.embeddings import build_embeddings
from lead_qualifier.ports.clock import SystemClock
from lead_qualifier.services.kb import IngestResult, KnowledgeBaseService
from lead_qualifier.services.workspace_sync import sync_workspaces
from lead_qualifier.workspaces.loader import load_workspaces


async def run(settings: Settings, slug: str, *, force: bool = False) -> IngestResult:
    registry = load_workspaces(
        settings.workspaces_dir,
        app_env=settings.app_env,
        enabled=settings.enabled_workspace_slugs | {slug},
    )
    workspace = registry.get(slug)
    if workspace is None:
        raise SystemExit(f"Unknown workspace: {slug}")
    if not workspace.config.knowledge_base.enabled:
        raise SystemExit(f"Knowledge base is disabled for workspace {slug}")
    engine = create_engine(settings.database_url)
    try:
        clock = SystemClock()
        await sync_workspaces(engine, registry, clock)
        service = KnowledgeBaseService(engine, build_embeddings(settings), clock)
        kb_dir = workspace.path / workspace.config.knowledge_base.path
        return await service.ingest(slug, kb_dir, force=force)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("workspace", nargs="?")
    parser.add_argument(
        "--warm", action="store_true", help="only download/load the embedding model, then exit"
    )
    parser.add_argument("--force", action="store_true", help="re-embed every document")
    args = parser.parse_args(argv)
    if args.warm:
        build_embeddings(get_settings()).warm()
        print("embedding model ready")
        return 0
    if not args.workspace:
        parser.error("workspace is required unless --warm is given")
    result = asyncio.run(run(get_settings(), args.workspace, force=args.force))
    print(" ".join(f"{k}={v}" for k, v in result.as_dict().items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

.PHONY: up down logs test lint fmt schemas seed seed-reset e2e eval

up:
	docker compose up -d --build --wait

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

lint:
	cd apps/agent && uv run ruff check . ../../evals && uv run ruff format --check . ../../evals && uv run mypy
	pnpm --filter web lint && pnpm --filter web typecheck

fmt:
	cd apps/agent && uv run ruff format . && uv run ruff check --fix .

test:
	cd apps/agent && uv run pytest
	pnpm --filter web test

schemas:
	cd apps/agent && uv run python -m lead_qualifier.scripts.export_schemas
	pnpm --filter contracts generate

seed:
	docker compose run --rm agent python -m lead_qualifier.scripts.seed

seed-reset:
	docker compose run --rm agent python -m lead_qualifier.scripts.seed --reset

e2e: seed-reset
	pnpm --filter web e2e

# Qualification eval with the fake provider (offline, free). See evals/qualification/README.md.
eval:
	cd apps/agent && uv run python ../../evals/qualification/run.py

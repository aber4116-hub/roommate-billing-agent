.PHONY: install lint format test coverage web-test migrate run compose-config hadolint backup

install:
	uv sync --frozen --extra dev

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .

test:
	uv run pytest -q

coverage:
	uv run pytest --cov=roommate_billing --cov-report=term-missing --cov-fail-under=80

web-test:
	node --test web/tests/format.test.mjs

migrate:
	uv run alembic upgrade head

run:
	uv run uvicorn roommate_billing.main:app --host 127.0.0.1 --port 8000 --reload

compose-config:
	docker compose --env-file .env.example -f docker-compose.yml config --quiet
	docker compose --env-file .env.example -f docker-compose.dev.yml config --quiet

hadolint:
	hadolint Dockerfile

backup:
	./scripts/backup_postgres.sh

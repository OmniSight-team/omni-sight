.PHONY: setup infra-up infra-down lint format test dev clean

setup:
	uv sync --all-packages
	cd services/dashboard && pnpm install
	uv run pre-commit install

infra-up:
	docker compose -f docker-compose.dev.yml up -d

infra-down:
	docker compose -f docker-compose.dev.yml down

lint:
	uv run ruff check .
	uv run mypy .

format:
	uv run ruff format .

test:
	uv run pytest -q

dev:
	cd services/dashboard && pnpm dev

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf services/dashboard/.next

.PHONY: install test lint format typecheck check serve

install:
	uv sync

test:
	uv run pytest -q

lint:
	uv run ruff check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy

check: lint typecheck test

serve:          ## sobe o servidor MCP no stdio
	uv run iamed-mcp

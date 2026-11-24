.PHONY: install test lint prepare-histor

install:
	uv sync --group dev

test:
	uv run pytest

lint:
	uv run ruff check .

prepare-histor:
	uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml

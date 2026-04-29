.PHONY: setup dev run test check

setup:
	uv sync

dev:
	uv run streamlit run main.py --server.runOnSave true

run:
	uv run streamlit run main.py

test:
	uv run pytest -q

check:
	uv run ruff check .

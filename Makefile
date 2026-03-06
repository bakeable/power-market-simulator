.PHONY: install test lint serve

install:
	poetry install

test:
	poetry run pytest -v

lint:
	poetry run ruff check src/ tests/

serve:
	poetry run uvicorn api.main:app --reload

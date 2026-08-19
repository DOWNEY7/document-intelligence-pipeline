.PHONY: install test lint format run-api run-dashboard docker-up docker-down clean

install:
	pip install --upgrade pip
	pip install -e ".[dev]"

test:
	pytest tests/ -v --cov=src --cov-report=term-missing

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/
	ruff check src/ tests/ --fix

run-api:
	uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload

run-dashboard:
	streamlit run src/dashboard/app.py --server.port 8501

docker-up:
	docker-compose up --build -d

docker-down:
	docker-compose down

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov *.egg-info build dist

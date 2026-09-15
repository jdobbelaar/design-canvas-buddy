.PHONY: help install install-backend install-frontend \
	dev backend frontend \
	test test-backend test-frontend \
	lint format clean

help:
	@echo "Targets:"
	@echo "  make install          Install backend + frontend dependencies"
	@echo "  make backend          Run the FastAPI backend (reload) on :8000"
	@echo "  make frontend         Run the Vite frontend dev server on :8080"
	@echo "  make test             Run backend + frontend tests"
	@echo "  make test-backend     Run backend tests (pytest)"
	@echo "  make test-frontend    Run frontend tests (vitest)"
	@echo "  make lint             Lint the frontend"
	@echo "  make format           Format the frontend"
	@echo "  make clean            Remove backend/frontend build & cache artifacts"

install: install-backend install-frontend

install-backend:
	cd backend && uv sync

install-frontend:
	cd frontend && npm install

backend:
	cd backend && uv run uvicorn app.main:app --reload

frontend:
	cd frontend && npm run dev

test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest

test-frontend:
	cd frontend && npm run test

lint:
	cd frontend && npm run lint

format:
	cd frontend && npm run format

clean:
	rm -rf backend/.pytest_cache backend/.venv
	rm -rf frontend/dist frontend/node_modules

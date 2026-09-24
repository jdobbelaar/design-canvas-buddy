.PHONY: help install install-backend install-frontend install-e2e \
	dev backend frontend \
	test test-backend test-frontend test-integration test-e2e e2e \
	lint format clean observability-up observability-down

help:
	@echo "Targets:"
	@echo "  make install          Install backend + frontend dependencies"
	@echo "  make backend          Run the FastAPI backend (reload) on :8000"
	@echo "  make frontend         Run the Vite frontend dev server on :8080"
	@echo "  make test             Run backend + frontend tests"
	@echo "  make test-backend     Run backend tests (pytest)"
	@echo "  make test-integration Run integration tests against docker-compose.yaml (needs Docker; slow)"
	@echo "  make install-e2e      Install the e2e tests' dependencies and Chromium"
	@echo "  make e2e              Install what the e2e tests need, then run them (needs Docker)"
	@echo "  make test-e2e         Just run the e2e tests (after make install-e2e)"
	@echo "  make test-frontend    Run frontend tests (vitest)"
	@echo "  make observability-up    Start Grafana, Prometheus, Loki, Tempo, and the collector (needs Docker)"
	@echo "  make observability-down  Stop them (data is kept; see observability/README.md)"
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

# Not part of `make test`: needs Docker, builds the image, and takes minutes.
test-integration:
	cd backend && uv run pytest integration_tests -v

install-e2e:
	cd e2e && npm install && npm run install:browsers

# Not part of `make test`: needs Docker and a browser, and builds the image.
# Chromium only; `cd e2e && npm run test:all-browsers` adds Firefox and WebKit.
test-e2e:
	cd e2e && npm test

# One command from a fresh checkout. This must stay in .PHONY: there is an e2e/
# directory, and without it `make e2e` sees an existing file with no rule and
# silently does nothing ("Nothing to be done for `e2e'").
e2e: install-e2e test-e2e

# A separate Compose project from the app; see observability/README.md.
observability-up:
	docker compose -f observability/docker-compose.yaml up -d
	@echo "Grafana: http://localhost:3000   OTLP endpoint for apps: http://localhost:4318"

observability-down:
	docker compose -f observability/docker-compose.yaml down

lint:
	cd frontend && npm run lint

format:
	cd frontend && npm run format

clean:
	rm -rf backend/.pytest_cache backend/.venv
	rm -rf frontend/dist frontend/node_modules

# Convenience targets for the LLM Robotic Task-Planning Agent.
# Requires: Python 3.11, Node 20, (optionally) Docker + Docker Compose.

BACKEND := backend
FRONTEND := frontend

.DEFAULT_GOAL := help

.PHONY: help setup setup-backend setup-frontend dev dev-backend dev-frontend \
        test lint build up down logs clean benchmark

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: setup-backend setup-frontend ## Install backend + frontend dependencies

setup-backend: ## Create venv-free dev install of backend deps
	cd $(BACKEND) && pip install -r requirements-dev.txt

setup-frontend: ## Install frontend dependencies
	cd $(FRONTEND) && npm install

dev: ## Print how to run both dev servers (run dev-backend / dev-frontend in two shells)
	@echo "Run in two terminals:"
	@echo "  make dev-backend   # http://localhost:8000  (docs at /docs)"
	@echo "  make dev-frontend  # http://localhost:3000"

dev-backend: ## Run the FastAPI backend with autoreload
	cd $(BACKEND) && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend: ## Run the Next.js dev server
	cd $(FRONTEND) && npm run dev

test: ## Run the backend pytest suite
	cd $(BACKEND) && pytest

lint: ## Lint backend (ruff) and frontend (eslint + tsc)
	cd $(BACKEND) && ruff check app tests
	cd $(FRONTEND) && npm run lint && npm run typecheck

build: ## Type-check + build the frontend; check backend imports
	cd $(FRONTEND) && npm run build
	cd $(BACKEND) && python -c "import app.main"

benchmark: ## Run the 20-command benchmark suite and print the completion rate
	cd $(BACKEND) && python -c "from app.config import Settings; from app.services.benchmark import BenchmarkRunner; r=BenchmarkRunner(Settings()).run('heuristic'); print(f'passed {r.passed}/{r.total} ({r.completion_rate:.0%})')"

up: ## Build and start the full stack with Docker Compose
	docker compose up --build -d

down: ## Stop and remove the Docker Compose stack
	docker compose down

logs: ## Tail Docker Compose logs
	docker compose logs -f

clean: ## Remove caches and build artifacts
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache
	find $(BACKEND) -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf $(FRONTEND)/.next

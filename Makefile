# MediCare Platform — Management Commands

.PHONY: up down restart logs shell migrate seed test clean status

# ==================== STACK MANAGEMENT ====================

up:
	docker-compose up

up-detached:
	docker-compose up -d

down:
	docker-compose down

restart:
	docker-compose down && docker-compose up

rebuild:
	docker-compose down && docker-compose build --no-cache && docker-compose up

# ==================== LOGS ====================

logs:
	docker-compose logs -f

logs-api:
	docker-compose logs -f api

logs-celery:
	docker-compose logs -f celery_worker

logs-db:
	docker-compose logs -f postgres

# ==================== DATABASE ====================

migrate:
	docker exec -it medicare_api alembic upgrade head

migrate-down:
	docker exec -it medicare_api alembic downgrade -1

migrate-history:
	docker exec -it medicare_api alembic history

create-tables:
	docker exec -it medicare_api python -c "from database.connection import engine, Base; from database.models import *; Base.metadata.create_all(bind=engine); print('Tables created')"

db-shell:
	docker exec -it medicare_postgres psql -U medicare_admin -d medicare_v2

# ==================== API SHELL ====================

shell:
	docker exec -it medicare_api bash

# ==================== CELERY ====================

celery-status:
	docker exec -it medicare_celery celery -A celery_app inspect active

celery-purge:
	docker exec -it medicare_celery celery -A celery_app purge

# ==================== HEALTH CHECKS ====================

status:
	@echo "Checking all services..."
	@docker exec medicare_api curl -s http://localhost:8000/health || echo "API: DOWN"
	@docker exec medicare_redis redis-cli ping || echo "Redis: DOWN"
	@docker exec medicare_postgres pg_isready -U medicare_admin -d medicare_v2 || echo "Postgres: DOWN"

# ==================== CLEANUP ====================

clean:
	docker-compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

# ==================== HELP ====================

help:
	@echo "MediCare Platform Commands:"
	@echo ""
	@echo "  make up              — Start all services"
	@echo "  make up-detached     — Start in background"
	@echo "  make down            — Stop all services"
	@echo "  make restart         — Restart all services"
	@echo "  make rebuild         — Rebuild and restart"
	@echo ""
	@echo "  make logs            — Follow all logs"
	@echo "  make logs-api        — Follow API logs only"
	@echo "  make logs-celery     — Follow Celery logs only"
	@echo ""
	@echo "  make migrate         — Run database migrations"
	@echo "  make db-shell        — Open PostgreSQL shell"
	@echo "  make shell           — Open API container shell"
	@echo ""
	@echo "  make status          — Check all services health"
	@echo "  make clean           — Remove all containers and volumes"
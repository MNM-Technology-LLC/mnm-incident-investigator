# SPDX-License-Identifier: Apache-2.0
SHELL := /bin/sh
PYTHON ?= python3
UV ?= uv
MAVEN_BIN ?= mvn
COMPOSE ?= docker compose

.PHONY: setup up down reset logs test check smoke native

setup:
	$(PYTHON) scripts/setup_env.py

up: setup
	$(COMPOSE) up --build --detach --wait --wait-timeout 180
	@echo "Open http://127.0.0.1:$$(sed -n 's/^CONSOLE_PORT=//p' .env | tail -1)"

down:
	$(COMPOSE) down --remove-orphans

# Removes only this Compose project's local telemetry/evidence and resets controls.
# Model downloads are outside Compose and are preserved.
reset: setup
	$(COMPOSE) down --volumes --remove-orphans
	$(COMPOSE) up --build --detach --wait --wait-timeout 180

logs:
	$(COMPOSE) logs --follow --tail 100

check:
	$(UV) sync --frozen
	$(UV) run --frozen ruff check investigator tests scripts
	$(UV) run --frozen pytest -q -m "not integration and not live_model"

test: check
	$(MAVEN_BIN) -B -ntp -f services/pom.xml verify

smoke:
	$(COMPOSE) exec -T console python scripts/smoke.py --base-url http://127.0.0.1:8080 --mcp-url http://mcp:8001/mcp --orders-url http://orders-service:8081 --output /tmp/mnm-smoke-report.json

native: setup
	$(UV) sync --frozen
	$(UV) run --frozen python scripts/dev.py

.PHONY: up down health test-ns test-llm

COMPOSE ?= docker compose

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

health:
	@bash scripts/health.sh

test-ns:
	python3 -m unittest tests/test_ns_fusion.py

test-llm:
	python3 master/src/chat/test_reasoner_llm.py

.PHONY: up down health test-ns test-lineage test-bridge test-llm

COMPOSE ?= docker compose

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

health:
	@bash scripts/health.sh

test-ns:
	cd backend && python3 -m unittest -v test_ns_fusion.py

test-lineage:
	cd backend && python3 -m unittest -v test_fitness_lineage.py

test-bridge:
	python3 -m unittest discover -s tests -p 'test_bridge_relay.py' -v

test-llm:
	python3 master/src/chat/test_reasoner_llm.py

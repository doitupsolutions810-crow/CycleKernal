.PHONY: up down health test-ns test-llm build-ns

COMPOSE ?= docker compose

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

health:
	@bash scripts/health.sh

test-ns:
	PYTHONPATH=backend python3 -m unittest discover -s tests -p 'test_ns_fusion.py' -v

build-ns:
	python3 -m py_compile backend/ns_fusion.py backend/simulation_core.py src/bridge/ns_fusion.py master/src/bridge/ns_fusion.py

test-llm:
	python3 master/src/chat/test_reasoner_llm.py

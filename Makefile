# Alfred Makefile — Standardized Verification & Execution Harness

PYTHON ?= python
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest

.PHONY: all help install dev-install test test-unit test-security test-api check run dev diagnose clean

all: check

help:
	@echo "Alfred AI Assistant Build & Execution Harness"
	@echo "Targets:"
	@echo "  install        Install runtime dependencies"
	@echo "  dev-install    Install runtime & test dependencies"
	@echo "  test           Run all automated tests with pytest"
	@echo "  test-unit      Run unit tests for audio, wakeword, interrupt, memory, brain, integrations"
	@echo "  test-security  Run dynamic weekday passphrase and sensitive guard tests"
	@echo "  test-api       Run FastAPI daemon endpoint tests"
	@echo "  check          Run full test suite and system diagnostics"
	@echo "  run            Start the Alfred assistant daemon"
	@echo "  dev            Start Alfred in simulation/dev mode on port 8020"
	@echo "  diagnose       Run environment, audio, security, and database diagnostics"
	@echo "  clean          Remove Python cache files"

install:
	$(PIP) install -r requirements.txt

dev-install:
	$(PIP) install -r requirements.txt
	$(PIP) install -r requirements-dev.txt

test:
	$(PYTEST) -v tests/

test-unit:
	$(PYTEST) -v tests/test_audio_and_devices.py tests/test_wakeword_and_vad.py tests/test_interrupt.py tests/test_memory_and_skills.py tests/test_integrations.py tests/test_brain_and_i18n.py

test-security:
	$(PYTEST) -v tests/test_security_passphrase.py

test-api:
	$(PYTEST) -v tests/test_web_api.py

check: test diagnose

run:
	$(PYTHON) -m src.main

dev:
	$(PYTHON) -m src.main --simulation --host 0.0.0.0 --port 8020

diagnose:
	$(PYTHON) scripts/diagnose_system.py

clean:
	rm -rf __pycache__ .pytest_cache tests/__pycache__ src/__pycache__ src/*/__pycache__


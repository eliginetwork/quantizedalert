PYTHON ?= .venv/bin/python
RUFF ?= .venv/bin/ruff
MYPY ?= .venv/bin/mypy

.PHONY: lint type test test-strict ci clean

lint:
	$(RUFF) check .

type:
	$(MYPY) src/quantizedalert --ignore-missing-imports || true

test:
	$(PYTHON) -m pytest tests/ -q --timeout=60

# Strict: warnings become errors (catches the ridge LinAlgWarning and RuntimeWarning)
test-strict:
	$(PYTHON) -m pytest tests/ -q -W error::scipy.linalg.LinAlgWarning -W error::RuntimeWarning --timeout=60

ci: lint test

clean:
	rm -rf .ruff_cache .pytest_cache .coverage htmlcov
	find src -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find src -name "*.pyc" -delete 2>/dev/null; true

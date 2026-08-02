# Development and Quality Gates

## Install dependencies

Runtime-only installation:

```bash
python -m pip install -r requirements.txt
```

Development and CI installation:

```bash
python -m pip install -r requirements-dev.txt
```

The production container installs only `requirements.txt`. Test, lint, audit, and coverage tools are not included in the runtime image.

## Run tests

```bash
PYTHONPATH=. python -m pytest -q
```

Coverage gate used by CI:

```bash
PYTHONPATH=. python -m pytest -q \
  --cov=app \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=xml \
  --cov-fail-under=85
```

The suite runs on Python 3.11 and Python 3.12. The `pytest-asyncio` fixture loop scope is explicitly set to `function` in `pyproject.toml` so upgrades cannot silently change async fixture behavior.

## Static checks

Critical Ruff checks:

```bash
python -m ruff check app tests scripts
```

Type checks for safety-sensitive modules:

```bash
python -m mypy \
  app/security.py \
  app/execution.py \
  app/execution_policy.py \
  app/run_identity.py \
  app/statistical_validation.py
```

Bandit application scan:

```bash
python -m bandit -q -r app -ll
```

Production dependency audit:

```bash
python -m pip_audit -r requirements.txt --strict
```

These checks are blocking. CI does not use `continue-on-error` for test, quality, audit, or container jobs.

## Production container

Build:

```bash
docker build -t backtest-agent:local .
```

The runtime image:

- uses `python:3.11-slim-bookworm`
- installs only production dependencies
- runs as `10001:10001`
- exposes port `8016`
- has an HTTP health check
- forwards `SIGTERM` to Uvicorn through `exec`

Run:

```bash
docker run --rm -p 8016:8016 backtest-agent:local
```

Health check:

```bash
curl --fail http://127.0.0.1:8016/health
```

## GitHub Actions

The CI workflow contains independent blocking jobs:

1. tests and branch coverage on Python 3.11
2. tests and branch coverage on Python 3.12
3. Ruff, MyPy, and Bandit
4. production dependency audit
5. non-root production container build and health smoke test

Hourly Backtest first runs the complete test suite, then executes the scheduled simulation. Production execution-realism environment defaults are scoped only to the Backtest step so they cannot mutate test expectations.

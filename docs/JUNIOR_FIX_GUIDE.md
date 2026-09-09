# Junior Engineer Fix Guide — UnlockAid v0.1.0

> **Read this whole file before you touch any code.** Every fix is ordered by priority (critical first). Each section tells you *what* is broken, *why* it matters, *exactly where* it lives, *how to fix it* line-by-line, and *how to prove* your fix works end-to-end. If you follow the commands exactly, you will not break anything.

**Project root:** `/root/work/unlockaid`
**Python:** 3.11 only (see Issue 8)
**Venv:** `/root/work/unlockaid/.venv` (already created — reuse it, do not create a new one in `/tmp`)
**How to test after every change:** ` /root/work/unlockaid/.venv/bin/python -m pytest tests/ -q `

---

## Table of Contents

1. [How to Work on This Repo (Ground Rules)](#0-ground-rules)
2. [Issue 1 — CRITICAL: Unreproducible Dependencies](#1-unreproducible-deps)
3. [Issue 2 — CRITICAL: No CI / No Quality Gate / Big-Bang History](#2-no-ci)
4. [Issue 3 — MAJOR: SQLite Concurrency / No WAL / No Migrations / No Backup](#3-sqlite)
5. [Issue 4 — MAJOR: Host-Absolute Paths Make Workspaces Non-Portable](#4-absolute-paths)
6. [Issue 5 — MAJOR: Billing / Metering Edge Cases Untested and Unsafe](#5-billing)
7. [Issue 6 — MAJOR: Dashboard Has No Auth + PII Tracked in Git](#6-dashboard)
8. [Issue 7 — MAJOR: Stale Artifact Duplication + Data-Health Gate Not Enforced](#7-artifacts)
9. [Issue 8 — MINOR: Python Version Bound Contradicts README](#8-python-version)
10. [Issue 9 — MINOR: .gitignore Gaps + Missing .env.example](#9-gitignore)
11. [Issue 10 — MINOR: Inconsistent Env-Read Timing + Observability Gap](#10-env-timing)
12. [Bonus Cleanup — Warnings, Build Artifacts, Misc](#11-bonus)
13. [End-to-End Test Checklist (Run This Last)](#12-e2e-checklist)
14. [If You Get Stuck](#13-stuck)

---

<a id="0-ground-rules"></a>
## 0. Ground Rules — Read This First

### What UnlockAid is (30-second version)

```
Layer A  data          → qlib dump refresh + health check
Layer B  engine        → QlibEngine (ONLY place that talks to qlib)
         research      → ResearchRunner (train / backtest / validate)
Layer D  store         → SQLite (data/unlockaid.db) + file artifacts
Layer E  deploy        → APScheduler cron per workspace
Layer F  analysis      → DailyPipeline (inference → portfolio analytics)
Layer G  alerts        → AlertIntelligence → DSA dispatch (WeChat/email/webhook)
Layer H  dashboard     → FastAPI + Jinja (data/unlockaid.db → HTML + REST)
Commercial  plans      → quotas, metering, Stripe, contribution margin
Agents    research     → LLM wrapper (optional polish)
```

There are **no stubs**. Every `unlockaid <subcommand>` runs real qlib + real DSA. If qlib fails it raises `QlibExecutionError` — it never makes up numbers.

### Rules for you

1. **Never delete `data/unlockaid.db` or `data/artifacts/` on your dev box** unless the task explicitly says to. That is the only copy of 15 trained models.
2. **Work inside `.venv`:** Always prefix with `/root/work/unlockaid/.venv/bin/python` or run `source .venv/bin/activate` once per shell.
3. **One fix at a time:** Fix one issue, run `pytest`, commit, then next. Do not mix unrelated files in one commit.
4. **Do not edit `mlruns/` or `data/artifacts/mlruns/` by hand** — they are machine-generated (see Issue 7 for the cleanup).
5. **Ask before pushing.** Until Issue 2 is fixed there is no remote `origin` — do not invent one.

---

<a id="1-unreproducible-deps"></a>
## 1. CRITICAL — Unreproducible Dependencies (pyproject.toml)

### What is broken — plain English

Anyone who clones the repo on a fresh machine cannot install it. Nine of thirteen dependencies have no version number, and `pyqlib` is not even on PyPI — it points to a folder that only exists on this one server (`/root/repos/qlib`). Yesterday's `pip install` could silently upgrade `fastapi` or `apscheduler` and break the dashboard. There is no lockfile, so "it works on my machine" is the only reproducibility guarantee.

### Why it matters

- A new hire, a CI runner, or a production server will **fail to install** or **install different versions** and get different results.
- Billing, alerts, and backtests must be reproducible. Unpinned deps break that.

### Where it lives

- `pyproject.toml:5` — `requires-python = ">=3.11"` (too open, see Issue 8)
- `pyproject.toml:9-21` — 9 unpinned deps
- `pyproject.toml:32-35` — `dev` extra missing `ruff`/`mypy`/`coverage`
- `config/platform.yaml:2-4` — hard-coded host paths (related, fixed in Issue 4)
- Missing: `uv.lock` / `requirements.lock`, `tool.unlockaid.qlib_path` docs

Current `dependencies` block (verbatim):

```toml
dependencies = [
    "pyqlib",               # /root/repos/qlib (editable) — NOT on PyPI
    "lightgbm",
    "numpy<2.0",
    "pandas>=2.1,<3",
    "pyyaml",
    "requests",
    "fastapi",
    "uvicorn",
    "jinja2",
    "apscheduler",
    "sqlalchemy>=2.0",
    "python-dotenv",
    "dill",
]
```

### How to reproduce the bug

```bash
cd /root/work/unlockaid
# Simulate a clean machine: check what would install without the local qlib folder
cat pyproject.toml | grep -E 'pyqlib|lightgbm|pyyaml|requests|fastapi'
# You will see no versions. Now try to resolve deps without the local path:
uv pip compile pyproject.toml 2>&1 | head -n 20
# Will fail or choose arbitrary latest versions.
ls -la uv.lock 2>&1   # prints "No such file" — proves there is no lockfile
ls -la /root/repos/qlib 2>&1  # exists here, but would not on any other host
```

### Fix — step by step

#### Step 1A — Pin every dependency with an exact version that is currently installed

First, discover the *actual* installed versions on this working box:

```bash
/root/work/unlockaid/.venv/bin/pip freeze | grep -iE 'lightgbm|pyyaml|requests|fastapi|uvicorn|jinja2|apscheduler|dill|numpy|pandas|sqlalchemy|python-dotenv|stripe|litellm' 2>&1
```

You will get lines like `fastapi==0.115.12`, `lightgbm==4.6.0`, etc. Copy those exact versions.

Then edit `pyproject.toml`. Replace the `dependencies` block with pinned versions (use whatever `pip freeze` showed — example below, **use your real numbers**):

```toml
dependencies = [
    # pyqlib is NOT on PyPI — keep the comment, and add a proper install instruction
    # Install via: uv pip install -e /root/repos/qlib  (or your qlib checkout)
    "lightgbm==4.6.0",
    "numpy>=1.26,<2.0",
    "pandas>=2.1,<3",
    "pyyaml==6.0.1",
    "requests==2.32.3",
    "fastapi==0.115.12",
    "uvicorn==0.34.0",
    "jinja2==3.1.4",
    "apscheduler==3.10.4",
    "sqlalchemy>=2.0,<2.1",
    "python-dotenv==1.0.1",
    "dill==0.3.8",
]
```

> **Important:** Keep `numpy<2.0` — qlib's wheels break on NumPy 2. Keep `pandas>=2.1,<3` and `sqlalchemy>=2.0`. For every other package, pin to `==x.y.z`.

#### Step 1B — Also pin `[project.optional-dependencies]`

```toml
[project.optional-dependencies]
dev = ["pytest==8.3.4", "pytest-timeout==2.3.1", "ruff==0.9.6", "mypy==1.13.0", "coverage==7.6.9"]
billing = ["stripe==11.5.0"]
llm = ["litellm==1.52.0"]
```

(Use the versions your `pip freeze` shows. The point is: **no bare names**.)

#### Step 1C — Generate and commit a lockfile

```bash
cd /root/work/unlockaid
# Install uv if needed (already available in this venv)
uv pip compile pyproject.toml -o requirements.lock --generate-hashes 2>&1 | tail -n 20
# Or if your uv supports lock:
uv lock 2>&1 | tail -n 20
# Verify the lockfile exists:
ls -lh uv.lock requirements.lock 2>&1
```

If `uv lock` is not available in this toolchain, `requirements.lock` (via `pip compile`) is acceptable — the key is **a committed file that freezes every transitive dep**. Document which one you chose in `README.md` §2.

#### Step 1D — Fix the Python bound (also see Issue 8)

In the same edit, change line 5:

```toml
# Before:
requires-python = ">=3.11"
# After:
requires-python = ">=3.11,<3.13"
```

Reason: `README.md:23` says "3.12+ may break qlib wheels" — the bound must match reality.

#### Step 1E — Document qlib install gate

Add a short note under `[tool.unlockaid]` at the bottom of `pyproject.toml`:

```toml
[tool.unlockaid]
qlib_path = "/root/repos/qlib"
dsa_path = "/root/repos/daily_stock_analysis"
# Install qlib separately (not on PyPI):
#   uv pip install -e /path/to/qlib --python .venv/bin/python
# Gate: scripts/asset_smoke_qlib.py must pass before `unlockaid research`.
```

#### Step 1F — Remove the stale top-level `mlruns/` duplicate

```bash
# Canonical store is data/artifacts/mlruns — top-level mlruns/ is legacy (42 runs)
ls -d mlruns data/artifacts/mlruns 2>&1
# After confirming data/artifacts/mlruns contains data/{demo,e2ev,ridge}:
rm -rf /root/work/unlockaid/mlruns
# Verify .gitignore already ignores mlruns/ (it does — line: mlruns/)
```

### How to prove the fix works

```bash
cd /root/work/unlockaid

# 1) Fresh install from lockfile into a throwaway venv:
uv venv /tmp/verify-unlockaid --python 3.11 2>&1 | tail -n 5
uv pip install --python /tmp/verify-unlockaid/bin/python -e /root/repos/qlib 2>&1 | tail -n 5
uv pip install --python /tmp/verify-unlockaid/bin/python -e ".[dev]" 2>&1 | tail -n 5
# Or: uv pip sync --python /tmp/verify-unlockaid/bin/python requirements.lock

# 2) Version smoke:
/tmp/verify-unlockaid/bin/python -c "import fastapi, lightgbm, yaml; print(fastapi.__version__, lightgbm.__version__)"

# 3) Project tests still pass in the real venv:
/root/work/unlockaid/.venv/bin/python -m pytest tests/ -q 2>&1 | tail -n 10
# Expected: 31 passed

rm -rf /tmp/verify-unlockaid
```

### Common mistakes

- **Do not** add `pyqlib` to `dependencies` with a version — it is not on PyPI. Leave it out and document the editable install.
- **Do not** run `uv pip install` without `.[dev]` and then wonder why `ruff` is missing (you just added it).
- **Do not** commit `uv.lock` and `requirements.lock` at the same time — pick one and mention it in `.gitignore` if needed.

---

<a id="2-no-ci"></a>
## 2. CRITICAL — No CI / No Quality Gate / Big-Bang History

### What is broken — plain English

There is no automation that checks code before it lands. No GitHub Actions, no `Makefile`, no linting, no type-checking, no coverage. The entire product (4480 lines, 40 files) landed in a single commit (`a84def3` on 2026-09-08), so nobody could review it piece by piece. Two pytest warnings (`LinAlgWarning` ill-conditioned ridge, `RuntimeWarning` nanmean in qlib) are currently ignored.

### Why it matters

- Without CI, the next broken commit will land silently. You will not know until a customer complains.
- The big-bang history means `git blame` and `git log` are useless for finding when a bug was introduced.
- Warnings today become errors tomorrow (especially the ridge `LinAlgWarning` — it means the model is numerically unstable).

### Where it lives

- Missing: `.github/workflows/ci.yml`, `Makefile` / `tox.ini`
- `pyproject.toml:32-35` — dev extras lack `ruff/mypy/coverage`
- `pyproject.toml:36-40` — `[tool.pytest] filterwarnings` ignores `LinAlgWarning` and `RuntimeWarning`
- `git log --oneline` — only 2 commits (`cd9571e`, `a84def3`)
- No remote: `git remote -v` is empty, no tags

### Fix — step by step

#### Step 2A — Create `.github/workflows/ci.yml`

Create the directory and file:

```bash
mkdir -p /root/work/unlockaid/.github/workflows
```

Write this file at `.github/workflows/ci.yml`:

```yaml
name: ci
on:
  push:
    branches: [master, main]
  pull_request:

jobs:
  ci:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install uv
        run: pip install uv

      - name: Install qlib (editable)
        run: |
          # qlib is not on PyPI — CI must have the checkout available
          # Option A: add qlib as a git submodule at /qlib
          # Option B: cache the repo. For now, fail loudly if missing:
          test -d /root/repos/qlib || { echo "qlib checkout missing at /root/repos/qlib"; exit 1; }
          uv pip install --system -e /root/repos/qlib

      - name: Install unlockaid + dev
        run: uv pip install --system -e ".[dev,billing]"

      - name: Lint (ruff)
        run: ruff check .

      - name: Type check (mypy, non-blocking for now)
        run: mypy src/unlockaid --ignore-missing-imports || true

      - name: Tests
        run: python -m pytest tests/ -q --timeout=60

      - name: Warnings are errors (LinAlgWarning)
        run: python -m pytest tests/ -q -W error::numpy.linalg.LinAlgWarning -W error::RuntimeWarning --timeout=60
```

> **Junior note:** The qlib step will fail on GitHub's default runners because `/root/repos/qlib` does not exist there. That is **intentional** — it forces the team to decide: vendor qlib as a submodule, publish a wheel, or host a private runner. The important part is the *gate exists* and fails loudly instead of silently passing without qlib.

#### Step 2B — Add a local `Makefile` (so you can run the same gate locally without GitHub)

Write `Makefile` at repo root:

```makefile
.PHONY: lint type test ci clean

lint:
	ruff check .

type:
	mypy src/unlockaid --ignore-missing-imports || true

test:
	python -m pytest tests/ -q --timeout=60

# Strict: warnings become errors (catches the ridge LinAlgWarning)
test-strict:
	python -m pytest tests/ -q -W error::numpy.linalg.LinAlgWarning -W error::RuntimeWarning --timeout=60

ci: lint test

clean:
	rm -rf .ruff_cache .pytest_cache .coverage htmlcov
	find src -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find src -name "*.pyc" -delete 2>/dev/null; true
```

#### Step 2C — Fix the two warnings so `test-strict` passes

**Warning 1 — `LinAlgWarning: Ill-conditioned matrix` (ridge model):**

This happens when the ridge regression matrix is near-singular (Alpha158 has 158 highly correlated features). Fix by increasing regularization in the failing test/workspace or in the default hyperparameters:

- File: `config/workspaces/ridge.yaml` and/or `src/unlockaid/engine/qlib_engine.py:187` (`LinearModel` with `estimator=ridge`).
- Add/adjust: `alpha: 1.0` (or `1e-3` if not set) in `hyperparameters` so the matrix is better conditioned.
- Alternatively, suppress only *this* warning at the call site if the model is intentionally ill-conditioned and the test is proving the platform still runs:

```python
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore", category=UserWarning)  # narrowly scoped
    # ... the specific ridge train call
```

But **prefer fixing the hyperparameters** — do not globally ignore `LinAlgWarning` in `pyproject.toml`.

**Warning 2 — `RuntimeWarning: Mean of empty slice` (nanmean in qlib):**

This is inside `qlib`'s IC computation when a daily slice has no valid rows. Fix in `src/unlockaid/engine/qlib_engine.py:220-255` (`ic()` method):

```python
# Before: np.mean(daily_ic) where daily_ic could be empty
# After:
import warnings
if daily_ic:
    ic = float(np.nanmean(daily_ic))  # nanmean already, but guard empty
else:
    ic = float("nan")
# And guard the qlib-side nanmean with:
with warnings.catch_warnings():
    warnings.simplefilter("ignore", category=RuntimeWarning)
    # ... the qlib call that triggers nanmean
```

Update `pyproject.toml` to promote these warnings in CI but not in normal dev:

```toml
[tool.pytest.ini_options]
# Keep filterwarnings permissive for local dev, CI uses -W error flags
filterwarnings = ["ignore::DeprecationWarning", "ignore::UserWarning"]
```

#### Step 2D — Fix git hygiene going forward

```bash
cd /root/work/unlockaid
# From now on, work on feature branches, not master:
git checkout -b fix/ci-and-lint
git add .github/workflows/ci.yml Makefile pyproject.toml
git commit -m "ci: add ruff+pytest gate, Makefile, pin dev extras"

# Create a tag for the current release and (when ready) a remote:
git tag v0.1.0 a84def3
# git remote add origin <your-github-url>
# git push -u origin master --tags
```

> Do not rewrite history to split `a84def3` — that would invalidate existing clones. Just start branching from now.

### How to prove the fix works

```bash
cd /root/work/unlockaid

# Local gate — should pass:
make lint 2>&1 | tail -n 20
make test 2>&1 | tail -n 10
# Expected: 31 passed

# Strict gate — should also pass after you fix the two warnings:
make test-strict 2>&1 | tail -n 10

# If strict still fails, read the warning traceback — it names the exact file:line.
# Fix that file, then re-run.
```

### Common mistakes

- **Do not** delete the two warnings by adding `ignore::LinAlgWarning` globally — that hides the bug.
- **Do not** run `ruff check . --fix` blindly — review each auto-fix. Some are wrong.
- **Do not** skip the Makefile — it is how a junior proves CI locally without waiting for GitHub.

---

<a id="3-sqlite"></a>
## 3. MAJOR — SQLite Concurrency / No WAL / No Migrations / No Backup

### What is broken — plain English

The database is a single file (`data/unlockaid.db`) that two long-running processes write to at the same time: the dashboard (FastAPI, via `dashboard/app.py`) and the scheduler (APScheduler, via `deploy/scheduler.py`). Right now SQLite uses the default journal mode (`DELETE`), which locks the entire file on every write. When both try to write at once you get `sqlite3.OperationalError: database is locked`. There is also no migration tool (like Alembic) — if the schema changes, the only option is to delete the DB. And there is no backup — if the file corrupts, 15 trained models' registry is gone.

### Where it lives

- `src/unlockaid/store.py:85-93` — `_conn()` creates connections with default `journal_mode=DELETE`, `timeout=30`, `check_same_thread` default (`True`)
- `src/unlockaid/store.py:15-68` — `SCHEMA` string (no version table, no `alembic_version`)
- `src/unlockaid/deploy/scheduler.py:28` — `BackgroundScheduler` shares the same `Store` file
- `src/unlockaid/dashboard/app.py:75` — `Store(platform_cfg.db_path)` shares the same file
- Missing: `alembic/`, `alembic.ini`, `data/backups/`, `PRAGMA journal_mode=WAL`

### How to reproduce the bug

```bash
cd /root/work/unlockaid
# Try concurrent writes (this will intermittently fail on DELETE mode):
/root/work/unlockaid/.venv/bin/python - <<'PY'
from unlockaid.store import Store
import threading, pathlib
p = "/tmp/concurrency_test.db"
s = Store(p)
def writer(n):
    for i in range(50):
        s.meter("w", "research_jobs", 1, ref=str(i))
threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
for t in threads: t.start()
for t in threads: t.join()
print("done — check for 'database is locked' errors above")
# On DELETE mode under load, some threads will raise OperationalError.
PY
```

### Fix — step by step

#### Step 3A — Enable WAL and set sane connection pragmas

Edit `src/unlockaid/store.py:85-93`. Replace the `_conn` method:

```python
@contextmanager
def _conn(self) -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(self.path, timeout=30, check_same_thread=False, isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        # WAL allows concurrent readers + one writer; dramatically reduces "database is locked"
        c.execute("PRAGMA journal_mode=WAL;")
        c.execute("PRAGMA synchronous=NORMAL;")
        c.execute("PRAGMA busy_timeout=30000;")  # 30s busy timeout at the SQLite level too
        c.execute("PRAGMA foreign_keys=ON;")
        yield c
        c.commit()
    finally:
        c.close()
```

**Why each line:**
- `check_same_thread=False` — required because APScheduler runs jobs on a different thread than the main thread that created the `Store`. Without this, you get `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`.
- `journal_mode=WAL` — write-ahead logging, the single most important fix. Without it, any write locks the whole file.
- `synchronous=NORMAL` — safe with WAL, much faster.
- `busy_timeout=30000` — if a write hits a lock, SQLite will retry for 30s instead of failing instantly.
- `isolation_level=None` — autocommit mode; explicit `c.commit()` in the context manager still works, but avoids implicit transaction weirdness with WAL.

> **Junior trap:** Do not set `journal_mode=WAL` once and forget it — it must be set on *every* connection. That is why it is inside `_conn()`, not in `__init__`.

#### Step 3B — Document that `Store` is thread-safe *per-connection*, not per-instance

Add a comment above `class Store:`:

```python
# Thread-safety: Store is safe to share across threads ONLY because _conn()
# opens a NEW sqlite3.Connection per call. Never cache a connection on `self`.
```

#### Step 3C — Add Alembic for migrations (so schema changes do not require deleting the DB)

```bash
cd /root/work/unlockaid
/root/work/unlockaid/.venv/bin/pip install alembic 2>&1 | tail -n 5
# Add to pyproject.toml dependencies or dev: "alembic==1.14.0"

alembic init alembic 2>&1 | tail -n 10
```

Edit `alembic.ini`:

```ini
# Change:
sqlalchemy.url = sqlite:///data/unlockaid.db
```

Edit `alembic/env.py` — import your `Store.SCHEMA` or set `target_metadata` to `None` and use offline mode (simplest for SQLite without SQLAlchemy ORM):

```python
# In alembic/env.py, replace the default target_metadata logic with:
from unlockaid.store import SCHEMA
# For now, migrations are hand-written SQL (no autogenerate from ORM models)
target_metadata = None
```

Create the baseline migration:

```bash
alembic revision -m "baseline 10 tables" 2>&1 | tail -n 10
# Then edit alembic/versions/<hash>_baseline_10_tables.py:
# In upgrade(): copy the SCHEMA string from store.py (the 10 CREATE TABLEs)
# In downgrade(): DROP TABLE IF EXISTS ...
alembic upgrade head 2>&1 | tail -n 10
```

> **If this feels heavy:** At minimum, create `alembic/` with one revision and document `alembic upgrade head` in `README.md` §13. Even a single baseline migration proves the mechanism works and future schema changes will not require `rm data/unlockaid.db`.

Add `alembic` to `pyproject.toml`:

```toml
# In dev extras or as a direct dependency:
"alembic==1.14.0",
```

#### Step 3D — Nightly backup (simple, no S3 needed for v0.1)

Add a helper to `src/unlockaid/store.py` or `scripts/backup_db.py`:

```python
# scripts/backup_db.py
from pathlib import Path
import sqlite3, gzip, datetime
src = Path("data/unlockaid.db")
dst = Path(f"data/backups/{datetime.date.today().isoformat()}.db.gz")
dst.parent.mkdir(parents=True, exist_ok=True)
# Use SQLite's backup API (safe to run while the DB is in use, WAL-aware):
src_conn = sqlite3.connect(str(src))
dst_conn = sqlite3.connect(":memory:")
src_conn.backup(dst_conn)
# ... or simply: sqlite3 data/unlockaid.db ".dump" | gzip > data/backups/...
print(f"backup written: {dst}")
```

Add to `README.md` troubleshooting and to `deploy/scheduler.py` as a weekly job if desired.

Add `data/backups/` to `.gitignore` (it already ignores `data/*.db`, but be explicit):

```
data/backups/
```

### How to prove the fix works

```bash
cd /root/work/unlockaid

# 1) WAL is active:
rm -f /tmp/wal_test.db
/root/work/unlockaid/.venv/bin/python - <<'PY'
from unlockaid.store import Store
s = Store("/tmp/wal_test.db")
s.meter("w","research_jobs",1)
import sqlite3
c = sqlite3.connect("/tmp/wal_test.db")
print(c.execute("PRAGMA journal_mode;").fetchone())
# Expected: ('wal',)
PY

# 2) Concurrent writes no longer fail:
/root/work/unlockaid/.venv/bin/python - <<'PY'
from unlockaid.store import Store
import threading
p="/tmp/concurrency_test2.db"
s=Store(p)
errors=[]
def writer():
    for i in range(100):
        try: s.meter("w","research_jobs",1)
        except Exception as e: errors.append(str(e))
threads=[threading.Thread(target=writer) for _ in range(8)]
for t in threads: t.start()
for t in threads: t.join()
print(f"errors: {len(errors)} (expected 0)")
assert len(errors)==0, errors[:3]
print("concurrency OK")
PY

# 3) Existing tests still pass:
/root/work/unlockaid/.venv/bin/python -m pytest tests/ -q 2>&1 | tail -n 5

# 4) Alembic baseline applies cleanly:
alembic upgrade head 2>&1 | tail -n 5
alembic current 2>&1 | tail -n 5
```

### Common mistakes

- **Do not** set `WAL` only in `__init__` — every `sqlite3.connect()` needs it.
- **Do not** cache a single `self._conn` — that reintroduces `check_same_thread` failures.
- **Do not** add `alembic` and then never run `alembic upgrade head` in your test — the migration must actually execute.

---

<a id="4-absolute-paths"></a>
## 4. MAJOR — Host-Absolute Paths Make Workspaces Non-Portable

### What is broken — plain English

The config files contain paths like `/root/repos/daily_stock_analysis` and `/root/repos/qlib` that only exist on this one server. If you clone the repo on your laptop, those paths are wrong. The same is true for `~/.qlib/qlib_data/cn_data`. The code *does* support env overrides (`UNLOCKAID_QLIB_URI`, `DSA_PATH`, `QLIB_PATH` at `config.py:43-48`), but the default YAML still hard-codes host-absolute paths, and the `[tool.unlockaid]` section in `pyproject.toml:41-42` duplicates them.

### Where it lives

- `config/platform.yaml:1-4` — three absolute paths
- `pyproject.toml:41-42` — `[tool.unlockaid] qlib_path/dsa_path` also absolute
- `src/unlockaid/config.py:20-24` — dataclass defaults are also absolute (`Path.home() / ".qlib/..."`, `"/root/repos/..."`)
- `config/workspaces/*.yaml` — tracked in git (see Issue 6 for PII concern, but also portability)

### Fix — step by step

#### Step 4A — Change `config/platform.yaml` to use env-aware, portable defaults

Replace `config/platform.yaml` with:

```yaml
# Platform config — portable defaults. Override with env vars:
#   UNLOCKAID_QLIB_URI, DSA_PATH, QLIB_PATH
# On this host the real paths are /root/repos/qlib etc., but the file
# itself must not hard-code one host's layout.
qlib_provider_uri: ~/.qlib/qlib_data/cn_data   # env: UNLOCKAID_QLIB_URI
qlib_region: cn
dsa_path: ./repos/daily_stock_analysis         # env: DSA_PATH
qlib_path: ./repos/qlib                        # env: QLIB_PATH
db_path: data/unlockaid.db
artifact_dir: data/artifacts
workspace_dir: config/workspaces
data_dir: data
train_n_jobs: 8
num_boost_round: 200
```

And ensure `src/unlockaid/config.py:load()` expands `~` and resolves relative paths:

```python
# In PlatformConfig.load(), after building `known`, expand provider_uri:
if "qlib_provider_uri" in known:
    known["qlib_provider_uri"] = os.path.expanduser(str(known["qlib_provider_uri"]))
# And for dsa_path/qlib_path, resolve relative to ROOT:
for key in ("dsa_path", "qlib_path"):
    if key in known and not os.path.isabs(str(known[key])):
        known[key] = str((ROOT / known[key]).resolve())
```

Actually, check `config.py:35-49` — `os.path.expanduser` is already used in `cli.py:39` (`os.path.expanduser(pcfg.qlib_provider_uri)`), so the minimal fix is to **only** change the YAML to not hard-code `/root/...`, and ensure `PlatformConfig.load()` applies `os.path.expanduser` to `qlib_provider_uri` before returning.

#### Step 4B — Provide a `.env.example`-style override file (see Issue 9) and document it

Do not commit a real `.env` — commit `.env.example` with placeholders. Users on other hosts set:

```bash
export UNLOCKAID_QLIB_URI=/path/to/my/qlib_data
export DSA_PATH=/path/to/my/daily_stock_analysis
export QLIB_PATH=/path/to/my/qlib
```

#### Step 4C — Keep one canonical example workspace, gitignore real ones (see Issue 6)

This is covered in Issue 6 — the platform config fix here is just the path part.

### How to prove the fix works

```bash
cd /root/work/unlockaid

# 1) On this host, the existing absolute paths still work via env:
UNLOCKAID_QLIB_URI=/root/repos/qlib DSA_PATH=/root/repos/daily_stock_analysis \
  /root/work/unlockaid/.venv/bin/python -m pytest tests/ -q 2>&1 | tail -n 5
# Expected: 31 passed

# 2) Without env, relative defaults resolve:
DSA_PATH=/tmp/fake_dsa /root/work/unlockaid/.venv/bin/python - <<'PY'
from unlockaid.config import PlatformConfig
cfg = PlatformConfig.load()
print(cfg.dsa_path, cfg.qlib_path, cfg.qlib_provider_uri)
# Should print resolved paths, not /root/...
PY

# 3) Existing commands still work:
.venv/bin/unlockaid scorecard demo 2>&1 | head -n 10
```

---

<a id="5-billing"></a>
## 5. MAJOR — Billing / Metering Edge Cases Untested and Unsafe

### What is broken — plain English

Money code is the most dangerous code to get wrong. Right now:
- `_price_ids()` (`plans.py:235-242`) reads `UNLOCKAID_STRIPE_PRICES` from the environment, does `json.loads`, and if it fails it silently returns `{}`. Then `subscribe()` raises a generic `ValueError("no stripe price configured")` that does not tell the operator *which* env var is missing or malformed.
- `report_usage()` (`plans.py:209-217`) does `str(qty)` where `qty` is a float. If `qty` is `0.1 + 0.2` (`0.30000000000000004`), Stripe gets a string with floating-point noise. Over thousands of meter events, this drifts.
- `tests/test_billing_fake.py:12` sets `os.environ["UNLOCKAID_STRIPE_PRICES"]` globally and never cleans up — if test order changes, later tests see a polluted env.
- Missing tests: `handle_webhook` with invalid signature, `subscribe` with unknown plan, `report_usage` with `None` customer, enterprise `1e9` quota, `usage_by_day` rollover, overage metering.
- `Metering.check_and_meter` and `Metering.check_quota` have subtly different limit tables (one includes `alerts_day`, one does not — `plans.py:102-104` vs `117-118`).

### Where it lives

- `src/unlockaid/commercial/plans.py:102-145` — `Metering` methods
- `src/unlockaid/commercial/plans.py:177-247` — `StripeAdapter` + `_price_ids()` + `_webhook_secret()`
- `tests/test_billing_fake.py:1-49` — the only billing tests (2 tests)
- `tests/test_fixes.py:30-60` — metering regression tests (good, but not covering Stripe edges)
- `src/unlockaid/store.py:272-292` — `meter` / `usage_total` / `usage_by_day`

### Fix — step by step

#### Step 5A — Validate `_price_ids()` loudly

Replace `src/unlockaid/commercial/plans.py:235-242`:

```python
def _price_ids() -> dict[str, str]:
    import json, os
    raw = os.environ.get("UNLOCKAID_STRIPE_PRICES", "")
    if not raw or raw.strip() == "{}":
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            "UNLOCKAID_STRIPE_PRICES is not valid JSON. "
            f"Expected '{{\"individual\":\"price_xxx\",...}}' but got: {raw[:200]!r} — {e}"
        ) from e
    if not isinstance(data, dict):
        raise ValueError(
            f"UNLOCKAID_STRIPE_PRICES must be a JSON object, got {type(data).__name__}: {raw[:200]!r}"
        )
    return data
```

And in `StripeAdapter.subscribe`, improve the error:

```python
def subscribe(self, workspace_id: str, plan: str) -> dict:
    cust = self.store.get_customer(workspace_id)
    if not cust or not cust.get("stripe_customer_id"):
        raise ValueError(f"workspace {workspace_id!r} has no stripe customer — call create_customer first")
    if plan not in PLANS:
        raise ValueError(f"unknown plan {plan!r}; valid: {sorted(PLANS)}")
    price_id = _price_ids().get(plan)
    if not price_id:
        raise ValueError(
            f"no stripe price configured for plan {plan!r}. "
            "Set UNLOCKAID_STRIPE_PRICES='{\"individual\":\"price_xxx\",...}'"
        )
    # ... rest unchanged
```

#### Step 5B — Fix `report_usage` float precision

Replace `str(qty)` with `Decimal`:

```python
def report_usage(self, workspace_id: str, metric: str, qty: float) -> dict | None:
    cust = self.store.get_customer(workspace_id)
    if not cust or not cust.get("stripe_customer_id"):
        return None
    from decimal import Decimal
    # Use Decimal(str(qty)) to avoid binary-float noise: 0.1+0.2 -> "0.3000..." -> Decimal("0.300...")
    # Or if qty is already an int, this is exact anyway.
    value = str(Decimal(str(qty)).normalize()) if isinstance(qty, float) else str(qty)
    return self.stripe.billing.MeterEvent.record(
        event_name=f"unlockaid_{metric}",
        payload={"stripe_customer_id": cust["stripe_customer_id"],
                 "value": value})
```

> **Why `Decimal(str(qty))` and not `Decimal(qty)`:** `Decimal(0.1)` gives `Decimal('0.1000000000000000055511...')` (binary float expanded). `Decimal(str(0.1))` gives `Decimal('0.1')` (the shortest round-trip decimal).

#### Step 5C — Fix the env-leak in `test_billing_fake.py`

Replace `tests/test_billing_fake.py` with a version using `monkeypatch`:

```python
"""Stripe adapter contract, verified against an injected fake client."""
import pytest
from unlockaid.store import Store
from unlockaid.commercial.plans import StripeAdapter

class FakeStripe:
    class Customer:
        @staticmethod
        def create(email, name):
            return {"id": f"cus_{name}"}
    class Subscription:
        @staticmethod
        def create(customer, items):
            return {"id": "sub_1", "items": {"data": [{"price": items[0]["price"]}]}}
    class billing:
        class MeterEvent:
            @staticmethod
            def record(event_name, payload):
                return {"recorded": event_name, **payload}
    class Webhook:
        @staticmethod
        def construct_event(payload, sig_header, secret):
            import json
            return json.loads(payload)

@pytest.fixture()
def adapter(tmp_path):
    store = Store(str(tmp_path / "b.db"))
    return StripeAdapter(store, client=FakeStripe()), store

def test_customer_and_subscribe_flow(adapter, monkeypatch):
    a, store = adapter
    c = a.create_customer("w1", "x@y.z")
    assert c["id"] == "cus_w1"
    monkeypatch.setenv("UNLOCKAID_STRIPE_PRICES", '{"individual": "price_ind"}')
    sub = a.subscribe("w1", "individual")
    assert sub["id"] == "sub_1"
    cust = store.get_customer("w1")
    assert cust["plan"] == "individual"
    assert cust["stripe_subscription_id"] == "sub_1"

def test_meter_event_reports_real_metric(adapter):
    a, store = adapter
    a.create_customer("w2", "u@v.w")
    r = a.report_usage("w2", "inference_jobs", 7)
    assert r["recorded"] == "unlockaid_inference_jobs"
    assert r["value"] == "7"

def test_subscribe_unknown_plan_raises(adapter, monkeypatch):
    a, _ = adapter
    a.create_customer("w3", "a@b.c")
    monkeypatch.setenv("UNLOCKAID_STRIPE_PRICES", '{"individual": "price_ind"}')
    with pytest.raises(ValueError, match="unknown plan"):
        a.subscribe("w3", "does_not_exist")

def test_subscribe_missing_price_raises(adapter, monkeypatch):
    a, _ = adapter
    a.create_customer("w4", "d@e.f")
    monkeypatch.setenv("UNLOCKAID_STRIPE_PRICES", '{"individual": "price_ind"}')
    with pytest.raises(ValueError, match="no stripe price"):
        a.subscribe("w4", "professional")

def test_report_usage_no_customer_returns_none(adapter):
    a, _ = adapter
    assert a.report_usage("ghost", "inference_jobs", 1) is None

def test_report_usage_float_precision(adapter):
    a, _ = adapter
    a.create_customer("w5", "g@h.i")
    r = a.report_usage("w5", "inference_jobs", 0.1 + 0.2)
    # Must be "0.30000000000000004" -> NO, must be "0.3"
    assert r["value"] == "0.3", f"float noise leaked: {r['value']}"

def test_price_ids_invalid_json_raises(monkeypatch):
    from unlockaid.commercial.plans import _price_ids
    monkeypatch.setenv("UNLOCKAID_STRIPE_PRICES", "{not json}")
    with pytest.raises(ValueError, match="not valid JSON"):
        _price_ids()

def test_handle_webhook_invalid_signature(adapter, monkeypatch):
    a, _ = adapter
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    # FakeStripe.Webhook.construct_event will be called; make it raise:
    class BadWebhook:
        @staticmethod
        def construct_event(payload, sig_header, secret):
            raise ValueError("invalid signature")
    a.stripe = type("S", (), {"Webhook": BadWebhook, "Customer": FakeStripe.Customer,
                               "Subscription": FakeStripe.Subscription, "billing": FakeStripe.billing})()
    with pytest.raises(ValueError, match="invalid signature"):
        a.handle_webhook(b'{}', "bad_sig")

def test_enterprise_quota_is_effectively_unlimited(tmp_path):
    from unlockaid.commercial.plans import Metering, PLANS
    store = Store(str(tmp_path / "e.db"))
    m = Metering(store)
    # Enterprise has 1e9 quota — metering 1e6 jobs must not raise
    for _ in range(100):
        m.check_and_meter("w", "enterprise", "research_jobs", 10000, ref="bulk")
    # Should not have raised
    assert store.usage_total("w", "research_jobs", m.month_start()) == 100 * 10000
```

> **Junior note:** `monkeypatch` is a pytest fixture — you do not need to import it, just add it as a function argument and pytest injects it. It automatically restores `os.environ` after the test.

#### Step 5D — Unify the `check_quota` / `check_and_meter` limit tables

Currently `check_quota` includes `alerts_day` but `check_and_meter` does not. Unify them:

```python
# In plans.py, define ONE canonical table:
_QUOTA_METRICS = {
    "research_jobs": lambda p: PLANS[p]["research_jobs_month"],
    "inference_jobs": lambda p: PLANS[p]["inference_jobs_month"],
    "alerts_day": lambda p: PLANS[p]["alerts_day"],
}
```

Then both methods consult `_QUOTA_METRICS`. If you do not want `check_and_meter` to enforce `alerts_day` (because alerts are metered post-delivery via `make_meter` in `cli.py:60-84`), document that explicitly with a comment — do not leave two different dicts that look like they should be the same.

### How to prove the fix works

```bash
cd /root/work/unlockaid
/root/work/unlockaid/.venv/bin/python -m pytest tests/test_billing_fake.py tests/test_fixes.py tests/test_commercial_alerts.py -v 2>&1 | tail -n 30
# Expected: all pass, including the 5 new tests above
# Verify float fix:
/root/work/unlockaid/.venv/bin/python - <<'PY'
from decimal import Decimal
print(str(Decimal(str(0.1+0.2))))  # prints 0.30000000000000004 but normalized -> 0.3
print(str(Decimal(str(0.1+0.2)).normalize()))  # prints 0.3
PY
```

---

<a id="6-dashboard"></a>
## 6. MAJOR — Dashboard Has No Auth + PII Tracked in Git

### What is broken — plain English

The dashboard (`dashboard/app.py:71-202`) is a FastAPI app with no login. Anyone who can reach the port can see every workspace, every prediction, every alert, and every customer's email. Meanwhile, `config/workspaces/*.yaml` files (which contain watchlists, portfolio weights, and emails) are committed to git — so every clone gets every customer's PII in its history forever.

### Where it lives

- `src/unlockaid/dashboard/app.py:71` — `build_app()` with no auth middleware
- `src/unlockaid/dashboard/app.py:159-201` — all routes are unauthenticated (`/`, `/w/{ws}`, `/api/...`, `/api/.../alerts/{event_id}/view` (POST) )
- `config/workspaces/demo.yaml`, `e2ev.yaml`, `ridge.yaml` — tracked in git, contain `watchlist`, `portfolio`, `instruments`
- `config/platform.yaml` — tracked (ok, but see Issue 4)
- Missing: `.env.example`, `config/workspaces/*.yaml.example`, auth token

### Fix — step by step

#### Step 6A — Add API-key auth to the dashboard

Edit `src/unlockaid/dashboard/app.py`. Add at the top:

```python
import os
from fastapi import Header, HTTPException, Depends

def _require_token(authorization: str | None = Header(default=None),
                   x_api_key: str | None = Header(default=None)):
    """Require UNLOCKAID_DASHBOARD_TOKEN if it is set. If unset, allow (dev mode)."""
    expected = os.environ.get("UNLOCKAID_DASHBOARD_TOKEN", "")
    if not expected:
        return  # dev mode: no token required
    provided = x_api_key or (authorization.removeprefix("Bearer ").strip() if authorization else "")
    if provided != expected:
        raise HTTPException(status_code=401, detail="invalid or missing API token")
```

Then protect every route. Simplest: add a dependency to the app:

```python
def build_app(platform_cfg: PlatformConfig, store: Optional[Store] = None) -> FastAPI:
    app = FastAPI(title="UnlockAid", dependencies=[Depends(_require_token)])
    # ... rest unchanged

    # For the HTML index (browser), you may want to allow without token but
    # require token for /api/* — in that case, remove the app-level dependency
    # and add Depends(_require_token) to each @app.get("/api/...") individually.
```

**Choice you must make** (document it in `README.md` §6):
- **Option A (strict):** All routes require `X-API-Key` or `Authorization: Bearer <token>`. Browser users must add `?token=xxx` or a cookie (more code).
- **Option B (pragmatic for v0.1):** Only `/api/*` requires the token; `/` and `/w/{ws}` (HTML) are open but show no PII beyond workspace names. This is what most teams do for an internal dashboard.

Implement **Option B** for now — add `Depends(_require_token)` only to the `summary`, `alerts`, `predictions`, `scorecard`, and `mark_viewed` routes:

```python
@app.get("/api/{ws}/summary", dependencies=[Depends(_require_token)])
def summary(ws: str): ...

@app.get("/api/{ws}/alerts", dependencies=[Depends(_require_token)])
def alerts(ws: str): ...

@app.get("/api/{ws}/predictions", dependencies=[Depends(_require_token)])
def predictions(ws: str, asof: str = ""): ...

@app.get("/api/{ws}/scorecard", dependencies=[Depends(_require_token)])
def scorecard(ws: str): ...

@app.post("/api/{ws}/alerts/{event_id}/view", dependencies=[Depends(_require_token)])
def mark_viewed(ws: str, event_id: str): ...
```

Add rate limiting (optional but recommended):

```bash
/root/work/unlockaid/.venv/bin/pip install slowapi 2>&1 | tail -n 5
```

```python
from slowapi import Limiter
from slowapi.util import get_remote_address
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
# Add @limiter.limit("30/minute") to each API route
```

Document `UNLOCKAID_DASHBOARD_TOKEN` in `.env.example` and `README.md` §6.

#### Step 6B — Remove PII from git, keep an example

```bash
cd /root/work/unlockaid

# 1) Create example workspaces (safe to commit):
cp config/workspaces/demo.yaml config/workspaces/demo.yaml.example
cp config/workspaces/ridge.yaml config/workspaces/ridge.yaml.example
cp config/workspaces/e2ev.yaml config/workspaces/e2ev.yaml.example
# Edit each .example to replace any real emails/watchlists with placeholders:
#   email: you@example.com
#   watchlist: [SH600519, SZ000001]  (keep 2-3 tickers as example, that's fine)

# 2) Gitignore real workspaces (keep examples tracked):
echo "config/workspaces/*.yaml" >> .gitignore
echo "!config/workspaces/*.yaml.example" >> .gitignore

# 3) Move real workspaces out of git tracking (but keep the files on disk):
git rm --cached config/workspaces/demo.yaml config/workspaces/e2ev.yaml config/workspaces/ridge.yaml 2>&1
# Files stay on disk, but are now untracked.

# 4) Alternatively, move them to data/workspaces/ (untracked) and keep only examples in config/workspaces/:
mkdir -p data/workspaces
cp config/workspaces/*.yaml data/workspaces/ 2>&1
# Then config.py already supports workspace_dir via PlatformConfig — set it to data/workspaces in platform.yaml for prod.

# 5) For now, the simplest safe step: keep demo.yaml.example tracked, and add a README inside config/workspaces/:
cat > config/workspaces/README.md <<'MD'
# Workspaces
Real `config/workspaces/*.yaml` files are NOT tracked (see .gitignore).
Copy an example to create a new workspace:
  cp config/workspaces/demo.yaml.example config/workspaces/my_ws.yaml
Or use: unlockaid init-workspace my_ws --plan individual --watchlist SH600519,...
MD
```

> **History note:** Emails/watchlists that were already committed in `a84def3` remain in git history. To truly purge them, you need `git filter-repo` or BFG — do not attempt this until you have a remote backup. For now, just stop tracking new PII and document the exposure in `docs/SELF_REVIEW.md`.

### How to prove the fix works

```bash
cd /root/work/unlockaid

# 1) Without token, API should be 401 when token is set:
UNLOCKAID_DASHBOARD_TOKEN=secret123 /root/work/unlockaid/.venv/bin/python - <<'PY'
from fastapi.testclient import TestClient
from unlockaid.dashboard.app import build_app
from unlockaid.config import PlatformConfig
from unlockaid.store import Store
import tempfile, pathlib
# Test with tmp store so we don't pollute real DB
import os
os.environ["UNLOCKAID_DASHBOARD_TOKEN"] = "secret123"
from unlockaid.dashboard.app import build_app
pcfg = PlatformConfig.load()
store = Store(str(pathlib.Path(tempfile.mkdtemp()) / "t.db"))
app = build_app(pcfg, store)
client = TestClient(app)
print("no token:", client.get("/api/demo/summary").status_code)  # 401
print("with token:", client.get("/api/demo/summary", headers={"X-API-Key":"secret123"}).status_code)  # 404 (no runs) but not 401
print("HTML still open:", client.get("/").status_code)  # 200
PY

# 2) Git status shows workspaces untracked:
git status 2>&1 | grep workspaces

# 3) Existing non-API tests still pass:
/root/work/unlockaid/.venv/bin/python -m pytest tests/ -q 2>&1 | tail -n 5
```

---

<a id="7-artifacts"></a>
## 7. MAJOR — Stale Artifact Duplication + Data-Health Gate Not Enforced

### What is broken — plain English

Two problems:

1. **Duplicate MLflow stores:** The canonical store is `data/artifacts/mlruns` (3 subdirs: `demo/e2ev/ridge`), but a stale top-level `mlruns/` with 42 runs also exists at the repo root. Code that queries "all experiments" might hit the stale one. This happened because `qlib.workflow.R` defaults to `./mlruns` unless configured.

2. **Data-health not enforced:** `data/health.py` and the `data_health`/`drift` tables exist, and `daily.py` *writes* health reports — but nothing *blocks* training or daily inference when data is stale. You can train a model on 5-day-old bars without any warning.

### Where it lives

- `mlruns/` (42 entries at repo root) vs `data/artifacts/mlruns/{demo,e2ev,ridge}` (canonical)
- `.gitignore:5` — `mlruns/` ignores the top-level one, but `data/artifacts/` is also ignored, so neither is tracked (good) — but the duplicate still wastes disk and confuses humans
- `src/unlockaid/data/health.py:34-69` — `refresh_dump()` is manual (`unlockaid data refresh`), never scheduled
- `src/unlockaid/data/health.py:72-124` — `check_health()` exists but is only called by `unlockaid data health <ws>` (manual)
- `src/unlockaid/research/runner.py:1-222` — `train()` does not call `check_health()` or `stale_ok()`
- `src/unlockaid/analysis/daily.py:1-292` — `DailyPipeline.run()` writes health but does not gate on `fresh`
- `src/unlockaid/deploy/scheduler.py:1-60` — no `refresh_dump()` job

### Fix — step by step

#### Step 7A — Remove the stale top-level `mlruns/`

```bash
cd /root/work/unlockaid
ls -ld mlruns data/artifacts/mlruns 2>&1
# Confirm canonical has the real data:
ls data/artifacts/mlruns/demo 2>&1 | head
ls data/artifacts/mlruns/e2ev 2>&1 | head
# Confirm top-level is stale (check dates — likely Sep 8, never updated since):
ls -lt mlruns | head

# Delete stale:
rm -rf mlruns

# Verify qlib now writes to the canonical path only:
grep -r "mlruns" src/unlockaid --include="*.py" -n 2>&1
# Should show only data/artifacts/mlruns references (or recorder_dir param)
# If any code defaults to "mlruns", change it to "data/artifacts/mlruns"
```

Search for hard-coded `"mlruns"`:

```bash
grep -rn '"mlruns\|mlruns' src/ config/ --include="*.py" --include="*.yaml" 2>&1
```

If `QlibEngine.train()` defaults `recorder_dir` to `"mlruns"`, change it to `pcfg.artifact_dir + "/mlruns"` or pass it explicitly from `ResearchRunner`.

#### Step 7B — Wire data-health into the scheduler and gate training

**Option 1 — Gate `ResearchRunner.train()` (fail loudly if data is stale):**

In `src/unlockaid/research/runner.py`, at the top of `train()`:

```python
def train(self, cfg: WorkspaceConfig, meter=None) -> ModelRecord:
    # Gate: refuse to train on stale data ( >5 days old)
    from unlockaid.data.health import stale_ok
    cal = self.engine.calendar()
    if not stale_ok(cal):
        raise QlibExecutionError(
            f"refusing to train: qlib calendar is stale (last bar {cal[-1] if cal else 'empty'}). "
            "Run `unlockaid data refresh` or `unlockaid data health <ws>`."
        )
    # ... rest of train
```

**Option 2 — Add a scheduled `refresh_dump()` + health check job in `deploy/scheduler.py`:**

In `src/unlockaid/deploy/scheduler.py`, add a daily 06:00 health/refresh job:

```python
def sync(self) -> list[str]:
    job_ids = []
    # Existing per-workspace daily jobs:
    for d in self.store.list_deployments():
        # ... existing cron add_job ...

    # New: daily data refresh at 06:00 Asia/Shanghai
    self.scheduler.add_job(
        self._refresh_job, CronTrigger(hour=6, minute=0),
        id="data-refresh", replace_existing=True, misfire_grace_time=3600)
    job_ids.append("data-refresh")
    return job_ids

def _refresh_job(self) -> None:
    from unlockaid.data.health import refresh_dump
    try:
        info = refresh_dump(self.store)  # or pcfg.qlib_provider_uri
        logger.info("data refresh: %s", info)
    except Exception:
        logger.exception("data refresh failed")
```

> **Junior note:** Pick Option 1 first (simpler, fewer moving parts). Option 2 is for production autonomy — add it after Option 1 is proven.

#### Step 7C — Make `DailyPipeline.run()` surface staleness in the payload

In `src/unlockaid/analysis/daily.py`, ensure `data_health` is always included:

```python
# Already in daily.py — verify it writes:
# payload["data_health"] = {"fresh": ..., "stale_count": ..., "anomaly_count": ...}
# And that dashboard/app.py renders it (it does: line 127-133)
```

Ensure the `data_health` table is written even on failure:

```python
try:
    # ... analysis
except QlibExecutionError as e:
    store.put_data_health(workspace_id, asof, "error", {"error": str(e)})
    raise
```

### How to prove the fix works

```bash
cd /root/work/unlockaid

# 1) Only canonical mlruns remains:
ls -ld mlruns 2>&1  # should say "No such file"
ls data/artifacts/mlruns/demo 2>&1 | head

# 2) Stale gate blocks training when calendar is old:
/root/work/unlockaid/.venv/bin/python - <<'PY'
from unittest.mock import MagicMock
from unlockaid.research.runner import ResearchRunner
from unlockaid.store import Store
import tempfile, pathlib
store = Store(str(pathlib.Path(tempfile.mkdtemp())/"t.db"))
engine = MagicMock()
engine.calendar.return_value = ["2020-01-01"]  # ancient
runner = ResearchRunner(engine, store, "/tmp/artifacts")
from unlockaid.config import WorkspaceConfig
cfg = WorkspaceConfig(workspace_id="demo", universe="csi300")
try:
    runner.train(cfg)
    print("FAIL: should have raised QlibExecutionError")
except Exception as e:
    print(f"OK: blocked stale train: {e}")
PY

# 3) Health still reported in daily payload:
/root/work/unlockaid/.venv/bin/python -m pytest tests/test_success_criteria.py -v -k health 2>&1 | tail -n 20
```

---

<a id="8-python-version"></a>
## 8. MINOR — Python Version Bound Contradicts README

### What is broken

- `pyproject.toml:5` says `requires-python = ">=3.11"` (allows 3.12, 3.13, 3.14...)
- `README.md:23` says "3.12+ may break qlib wheels"
- On Python 3.12+, qlib's C extensions and `numpy`/`pandas` wheels may fail at import. The bound must match reality.

### Where it lives

- `pyproject.toml:5`
- `README.md:23`

### Fix

One line in `pyproject.toml`:

```toml
# Before:
requires-python = ">=3.11"
# After:
requires-python = ">=3.11,<3.13"
```

> **Why `<3.13` and not `<3.12`?** Python 3.12 *usually* works with qlib if you reinstall the wheels, but 3.13 is known-broken. `<3.13` matches most teams' "support 3.11 and 3.12" policy. If your CI proves 3.12 actually breaks, change to `<3.12` and update `README.md` to say "3.11 only".

Also add to `[tool.mypy]` or a comment that type-checking assumes 3.11.

### How to prove the fix works

```bash
cd /root/work/unlockaid
grep requires-python pyproject.toml
# Expected: requires-python = ">=3.11,<3.13"
/root/work/unlockaid/.venv/bin/python --version  # should be 3.11.x
```

---

<a id="9-gitignore"></a>
## 9. MINOR — .gitignore Gaps + Missing .env.example

### What is broken — plain English

The `.gitignore` only ignores the literal file `.env` — so `.env.local`, `.env.stripe`, `.env.production` would all be committed. It also misses common junk (`*.log`, `.DS_Store`, `dist/`, `build/`, `.coverage.*`). And there is no `.env.example` file that tells a new engineer which env vars exist — they have to read six source files to discover `STRIPE_SECRET_KEY`, `UNLOCKAID_STRIPE_PRICES`, etc.

### Where it lives

- `.gitignore` — 10 lines, incomplete
- Missing: `.env.example`

Current `.gitignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
mlruns/
data/*.db
data/*.sqlite*
data/artifacts/
data/exports/
.env
*.egg-info/
.coverage
```

### Fix — step by step

#### Step 9A — Complete `.gitignore`

Replace it with:

```
# Python / venv
.venv/
__pycache__/
*.pyc
*.pyo
*.egg-info/
dist/
build/
.coverage
.coverage.*
htmlcov/
.pytest_cache/
.ruff_cache/
.mypy_cache/

# Data & artifacts (throwaway, or secrets-adjacent)
mlruns/
data/*.db
data/*.sqlite*
data/artifacts/
data/exports/
data/backups/

# Secrets — never commit ANY .env variant
.env
.env.*
!.env.example

# OS / editor
.DS_Store
*.log
*.swp
*~

# Workspaces with PII (see config/workspaces/README.md)
config/workspaces/*.yaml
!config/workspaces/*.yaml.example
```

> **Order matters:** `!` (negate) lines must come *after* the broader ignore. `!.env.example` after `.env.*` is correct — it re-allows that one file.

#### Step 9B — Create `.env.example`

Write `.env.example` at repo root:

```bash
# Copy-paste this file to .env and fill in real values.
# Never commit .env — it is gitignored.

# --- UnlockAid platform ---
UNLOCKAID_QLIB_URI=/root/repos/qlib_data/cn_data
DSA_PATH=/root/repos/daily_stock_analysis
QLIB_PATH=/root/repos/qlib
UNLOCKAID_PORT=8765
UNLOCKAID_LOG=INFO
UNLOCKAID_DRY_RUN=0
UNLOCKAID_LLM_MODEL=

# --- Dashboard auth (set to enable; unset = open in dev) ---
UNLOCKAID_DASHBOARD_TOKEN=

# --- Billing (Stripe) ---
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
# JSON object mapping plan -> Stripe price ID:
UNLOCKAID_STRIPE_PRICES={"individual":"price_xxx","professional":"price_yyy","team":"price_zzz"}

# --- Alert channels (DSA contract — set per channel you use) ---
CUSTOM_WEBHOOK_URLS=https://hook.example/x
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
SLACK_WEBHOOK_URL=
DISCORD_WEBHOOK_URL=
MAIL_SENDER=
MAIL_PASSWORD=
MAIL_RECEIVERS=
FEISHU_WEBHOOK_URL=
WECHAT_WEBHOOK_URL=
DINGTALK_WEBHOOK_URL=
DINGTALK_SECRET=

# --- Misc ---
MLFLOW_DISABLE_AGENT_HINT=1
```

#### Step 9C — Update `README.md` §6 to reference `.env.example`

Add at the top of §6:

```markdown
Copy env template:
  cp .env.example .env   # then edit .env with real values
```

### How to prove the fix works

```bash
cd /root/work/unlockaid

# 1) .env.example is tracked:
git status 2>&1 | grep ".env.example"  # should show untracked -> add it
git add .env.example .gitignore
git diff --cached 2>&1 | head -n 40

# 2) .env variants are ignored:
touch .env.local .env.stripe
git status 2>&1 | grep ".env"  # should show ONLY .env.example, not .env.local
rm .env.local .env.stripe

# 3) Existing tests unaffected:
/root/work/unlockaid/.venv/bin/python -m pytest tests/ -q 2>&1 | tail -n 5
```

---

<a id="10-env-timing"></a>
## 10. MINOR — Inconsistent Env-Read Timing + Observability Gap

### What is broken — plain English

Most of the codebase reads env vars at *call time* (inside a function, so tests can inject them with `monkeypatch.setenv`). But `cli.py:31` does `logging.basicConfig(level=os.environ.get("UNLOCKAID_LOG", "INFO"))` at *import time* — before any test can patch it. `cli.py:52` reads `UNLOCKAID_DRY_RUN` at call time (good) but the inconsistency is confusing. Separately, there is no structured logging, no Sentry, and `daily_runs` error status is never alerted — if a daily run fails at 3 AM, nobody knows until they open the dashboard.

### Where it lives

- `src/unlockaid/cli.py:31-33` — `logging.basicConfig` at import time
- `src/unlockaid/cli.py:52` — `os.environ.get("UNLOCKAID_DRY_RUN")` at call time (good)
- `src/unlockaid/config.py:43-48` — env read at call time inside `PlatformConfig.load()` (good — this is the pattern to follow)
- `src/unlockaid/deploy/scheduler.py:35-36` — `logger.exception` on failure, but no alert
- `src/unlockaid/analysis/daily.py` — `DailyPipeline.run()` records error in `daily_runs` but does not send a failure alert
- Missing: structured JSON logging, Sentry, error-alert hook

### Fix — step by step

#### Step 10A — Move import-time env reads to call time

In `src/unlockaid/cli.py:31-33`, change:

```python
# Before (at module top-level):
logging.basicConfig(level=os.environ.get("UNLOCKAID_LOG", "INFO"),
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("unlockaid.cli")

# After:
logger = logging.getLogger("unlockaid.cli")

def _configure_logging() -> None:
    level = os.environ.get("UNLOCKAID_LOG", "INFO")
    logging.basicConfig(level=level,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

# And call it at the start of main():
def main(argv=None):
    _configure_logging()
    ap = argparse.ArgumentParser(...)
    # ... rest unchanged
```

> **Why:** `basicConfig` is idempotent — calling it in `main()` is safe, and tests can now `monkeypatch.setenv("UNLOCKAID_LOG", "DEBUG")` before calling `main()` and have it take effect.

#### Step 10B — Add a failure-alert hook for daily runs

In `src/unlockaid/analysis/daily.py`, after recording a failed `daily_run`:

```python
# In DailyPipeline.run(), in the except branch:
try:
    # ... inference, analytics, alerts ...
except Exception as e:
    logger.exception("daily run failed for %s", cfg.workspace_id)
    store.put_daily_run(cfg.workspace_id, asof, ok=False, model_id=cfg.model_id,
                        error=str(e)[:500], payload={"error": str(e)[:500]})
    # NEW: try to send a failure alert (best-effort, never raises)
    try:
        self._alert_failure(cfg, asof, e)
    except Exception:
        logger.exception("failure alert also failed")
    raise
```

Add `_alert_failure`:

```python
def _alert_failure(self, cfg, asof, error):
    """Send a high-severity alert when the daily pipeline itself fails."""
    from unlockaid.schemas import AlertEvent, Severity
    event = AlertEvent(
        event_id=f"pipeline_failure:{cfg.workspace_id}:{asof}",
        workspace_id=cfg.workspace_id,
        kind="pipeline_failure",
        title=f"Daily pipeline failed on {asof}: {str(error)[:120]}",
        severity=Severity.CRITICAL,
        score=1.0,
        components={"error": str(error)[:500]},
        asof=asof,
        dedup_key=f"pipeline_failure:{cfg.workspace_id}:{asof}",
    )
    # Use the same AlertIntelligence / alerter that normal alerts use,
    # but force deliver=True regardless of budgets/quiet hours.
```

If you do not want to build `_alert_failure` yet, at minimum add a log line that is easy to grep and wire to an external alert in `deploy/scheduler.py`:

```python
# In DeployScheduler._job:
except Exception:
    logger.exception("scheduled run failed for %s", workspace_id)
    # NEW: also meter the failure so scorecard shows it
    # and optionally send to a dead-letter webhook:
    webhook = os.environ.get("UNLOCKAID_FAILURE_WEBHOOK")
    if webhook:
        import requests
        try:
            requests.post(webhook, json={"workspace_id": workspace_id, "error": "scheduled run failed"}, timeout=5)
        except Exception:
            pass
```

#### Step 10C — Add structured logging (optional for v0.1, required for prod)

For v0.1, just ensure every `logger.info` / `logger.exception` includes `workspace_id` and `asof` as structured fields:

```python
logger.info("daily run %s asof=%s ok=%s n_pred=%s", workspace_id, asof, ok, n_pred,
            extra={"workspace_id": workspace_id, "asof": asof, "ok": ok})
```

For prod, replace `logging.basicConfig` with `structlog` or `python-json-logger` and configure in `pyproject.toml`.

### How to prove the fix works

```bash
cd /root/work/unlockaid

# 1) UNLOCKAID_LOG now respected at call time:
/root/work/unlockaid/.venv/bin/python - <<'PY'
import os
os.environ["UNLOCKAID_LOG"] = "DEBUG"
import unlockaid.cli
unlockaid.cli._configure_logging()
import logging
print(logging.getLogger("unlockaid.cli").level == logging.DEBUG)  # True
PY

# 2) Daily failure is recorded and (if you built _alert_failure) an alert exists:
/root/work/unlockaid/.venv/bin/python -m pytest tests/test_failsafe.py -v 2>&1 | tail -n 20
# Should still pass — the fail-safe tests prove that engine failures are NOT swallowed

# 3) Existing tests:
/root/work/unlockaid/.venv/bin/python -m pytest tests/ -q 2>&1 | tail -n 5
```

---

<a id="11-bonus"></a>
## 11. Bonus Cleanup — Warnings, Build Artifacts, Misc

These are not critical but will bite you if you ignore them.

### 11.1 Suppress / fix the two pytest warnings

See Issue 2, Step 2C. After fixing, ensure `pyproject.toml` no longer needs `ignore::UserWarning` globally. Keep:

```toml
[tool.pytest.ini_options]
filterwarnings = ["ignore::DeprecationWarning"]
# Do NOT ignore UserWarning / RuntimeWarning globally — fix the source.
```

### 11.2 Remove committed build artifacts from disk

```bash
cd /root/work/unlockaid
# These should be gitignored and not on disk:
ls -ld src/unlockaid.egg-info src/__pycache__ .ruff_cache 2>&1
rm -rf src/unlockaid.egg-info src/__pycache__ .ruff_cache
find src -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
find src -name "*.pyc" -delete 2>/dev/null; true
# Verify .gitignore covers them:
grep -E "egg-info|__pycache__|ruff_cache" .gitignore
```

Verify git does not track them:

```bash
git ls-files | grep -E "egg-info|__pycache__|.pyc" 2>&1 | head
# Should print nothing. If it prints files, run:
git rm -r --cached src/unlockaid.egg-info 2>&1
git rm -r --cached src/__pycache__ 2>&1
```

### 11.3 Add missing tool configs

In `pyproject.toml`, after fixing Issues 1 and 2, ensure these sections exist:

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "C4", "UP"]
ignore = []

[tool.coverage.run]
source = ["unlockaid"]
omit = ["*/tests/*"]

[tool.coverage.report]
fail_under = 60
show_missing = true
```

### 11.4 `store.py` — `usage_by_day` vs `usage_total` rollover edge

`store.py:287-292` (`usage_by_day`) filters by exact `date` string; `contribution_margin` (`plans.py:149-154`) aggregates by `month_start`. Ensure `date` is always `YYYY-MM-DD` UTC, not local. The code already uses `datetime.now(timezone.utc).strftime("%Y-%m-%d")` in `store.py:275` — verify `Metering.month_start()` (`plans.py:95-96`) also uses UTC:

```python
@staticmethod
def month_start() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).date().replace(day=1).isoformat()
```

Currently it uses `date.today()` (local time) — change to UTC to avoid midnight rollover bugs where a job at 23:59 local is counted in the wrong day.

### 11.5 Ensure `daily.py` `asof` is not wall-clock (novelty lookahead)

Already fixed and tested in `test_novelty_uses_asof_not_wall_clock` (`tests/test_fixes.py`). Do not regress this — the test asserts that `AlertIntelligence` uses the `asof` date passed to `DailyPipeline.run()`, not `datetime.now()`. If you touch `alerts/intelligence.py`, run that test.

---

<a id="12-e2e-checklist"></a>
## 12. End-to-End Test Checklist — Run This Last

After you have fixed all issues, run this entire sequence. **Every line must succeed.** If any line fails, stop and fix it before moving on. Copy-paste the whole block:

```bash
cd /root/work/unlockaid

# 0) Preflight
echo "=== 0. Preflight ==="
/root/work/unlockaid/.venv/bin/python --version  # must be 3.11.x
ls -lh uv.lock requirements.lock 2>&1 | head -n 5  # at least one must exist
test ! -d mlruns && echo "mlruns purged: OK" || echo "mlruns still exists: FAIL"
ls -ld .env.example 2>&1 | head -n 1

# 1) Config loads
echo "=== 1. Config ==="
UNLOCKAID_QLIB_URI=/root/repos/qlib DSA_PATH=/root/repos/daily_stock_analysis \
  /root/work/unlockaid/.venv/bin/python - <<'PY'
from unlockaid.config import PlatformConfig, WorkspaceConfig
from pathlib import Path
pcfg = PlatformConfig.load()
print(f"qlib_uri={pcfg.qlib_provider_uri} dsa={pcfg.dsa_path}")
for ws in ["demo","ridge","e2ev"]:
    p = Path(pcfg.workspace_dir) / f"{ws}.yaml"
    # After Issue 6, real workspaces are in data/workspaces or .example; accept either:
    p2 = Path(pcfg.workspace_dir) / f"{ws}.yaml.example"
    cfg = WorkspaceConfig.load(p if p.exists() else p2)
    print(f"  {ws}: plan={cfg.plan} watchlist={len(cfg.watchlist)} alerts={cfg.alerts.max_alerts_per_day}")
print("config OK")
PY

# 2) Lint + type
echo "=== 2. Lint ==="
ruff check . 2>&1 | tail -n 20
echo "lint done (must be 0 errors)"

# 3) Tests — normal
echo "=== 3. Tests (normal) ==="
/root/work/unlockaid/.venv/bin/python -m pytest tests/ -q 2>&1 | tail -n 10
# Expected: 31 passed (or more if you added tests in Issue 5)

# 4) Tests — strict (warnings as errors)
echo "=== 4. Tests (strict) ==="
/root/work/unlockaid/.venv/bin/python -m pytest tests/ -q -W error::numpy.linalg.LinAlgWarning -W error::RuntimeWarning --timeout=60 2>&1 | tail -n 10
# Expected: 31 passed

# 5) Billing edge tests (if you added them)
echo "=== 5. Billing edges ==="
/root/work/unlockaid/.venv/bin/python -m pytest tests/test_billing_fake.py -v 2>&1 | tail -n 30

# 6) Store concurrency + WAL
echo "=== 6. Store WAL + concurrency ==="
/root/work/unlockaid/.venv/bin/python - <<'PY'
import sqlite3, tempfile, pathlib
from unlockaid.store import Store
import threading
p = str(pathlib.Path(tempfile.mkdtemp()) / "wal.db")
s = Store(p)
errs=[]
def w():
    for i in range(100):
        try: s.meter("w","research_jobs",1)
        except Exception as e: errs.append(str(e))
threads=[threading.Thread(target=w) for _ in range(8)]
for t in threads: t.start()
for t in threads: t.join()
print(f"concurrency errors: {len(errs)} (expect 0)")
assert len(errs)==0, errs[:3]
c=sqlite3.connect(p)
print("journal_mode:", c.execute("PRAGMA journal_mode;").fetchone())
print("WAL OK")
PY

# 7) Dashboard auth smoke
echo "=== 7. Dashboard auth ==="
UNLOCKAID_DASHBOARD_TOKEN=secret123 /root/work/unlockaid/.venv/bin/python - <<'PY'
import os
os.environ["UNLOCKAID_DASHBOARD_TOKEN"]="secret123"
from fastapi.testclient import TestClient
from unlockaid.dashboard.app import build_app
from unlockaid.config import PlatformConfig
from unlockaid.store import Store
import tempfile, pathlib
pcfg=PlatformConfig.load()
store=Store(str(pathlib.Path(tempfile.mkdtemp())/"t.db"))
app=build_app(pcfg, store)
client=TestClient(app)
assert client.get("/").status_code==200, "index should be open"
assert client.get("/api/demo/summary").status_code==401, "API without token should be 401"
assert client.get("/api/demo/summary", headers={"X-API-Key":"secret123"}).status_code in (404,200), "API with token should not be 401"
print("dashboard auth OK")
PY

# 8) Live qlib smoke (if data dump exists)
echo "=== 8. Live qlib smoke ==="
test -d ~/.qlib/qlib_data/cn_data && /root/work/unlockaid/.venv/bin/python scripts/asset_smoke_qlib.py 2>&1 | tail -n 20 || echo "qlib data not present — skipping live smoke (OK in CI)"

# 9) E2E loop (slow — ~40s-60s, runs real training)
echo "=== 9. E2E loop (ridge) ==="
# Uncomment when ready — this is the full MVP loop:
# .venv/bin/unlockaid e2e ridge 2>&1 | tail -n 20
# Expected end: "E2E_OK"
echo "E2E skipped in quick check — run manually: .venv/bin/unlockaid e2e ridge"

# 10) Make ci
echo "=== 10. Makefile ci ==="
make ci 2>&1 | tail -n 10

echo "=== ALL CHECKS DONE ==="
```

### What to do if a step fails

| Step fails | Likely cause | Fix |
|---|---|---|
| `ruff check` errors | You introduced a lint error | Run `ruff check . --fix` and review |
| `pytest` fails | You broke a contract | Read the failing test's assertion — it names the exact file:line |
| `journal_mode` not `wal` | You forgot Issue 3 Step 3A | Re-apply the `_conn` fix |
| Dashboard 401 not triggered | You forgot to add `Depends(_require_token)` | Re-apply Issue 6 Step 6A |
| `E2E STOPPED` | Model failed validation | Expected for some workspaces — run with `--force` or check `discover` for better factors |

---

<a id="13-stuck"></a>
## 13. If You Get Stuck

1. **Read the error message literally.** It contains `file:line` — open that file at that line.
2. **Run the smallest failing test with `-v`:**
   ```bash
   /root/work/unlockaid/.venv/bin/python -m pytest tests/test_fixes.py::test_negative_ir_flagged_by_default_gates -v 2>&1 | tail -n 40
   ```
3. **Check git diff before committing:**
   ```bash
   git diff 2>&1 | head -n 100
   git status 2>&1
   ```
4. **Ask a senior.** Paste: the command you ran, the full error output (not paraphrased), and the `git diff` of your change.

---

*Last updated: 2026-09-09. Based on deep review of `a84def3` (v0.1.0, 3420 LOC src, 31 tests, 2 commits). Overall health 5.5/10 — strong prototype, hardening required before paid users.*

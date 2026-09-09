# QuantizedAlert Portability & End-to-End Deployment Guide

This guide describes how to replicate, deploy, and run the **QuantizedAlert** project from scratch on any fresh Linux machine (Ubuntu 22.04+, Debian 12+, RHEL 9+, etc.).

---

## 1. LLM Usage & OpenAI-Compatible Configuration

### Does this project use LLMs?
**Yes, but strictly for natural-language prose explanation.**
- **All quant computations are 100% deterministic:** Factor computation (Alpha158), model training (LightGBM, Ridge, Lasso), signal inference, walk-forward validation, information ratio (IR), Sharpe, drawdown, portfolio concentration, and alert gating are executed using deterministic code (`qlib`, `numpy`, `pandas`, `scipy`). QuantizedAlert adheres to an **anti-quack principle**: LLMs **never** generate trading signals, predict numbers, or invent financial data.
- **Where LLMs are used:** Only in `ResearchExplanationAgent` (invoked by `quantizedalert explain <workspace> <model>`). It translates numerical backtest and validation metrics into plain English for non-specialist stakeholders.
- **Graceful Fallback:** If no LLM is configured or if the LLM endpoint is down, QuantizedAlert automatically and seamlessly outputs deterministic template prose tagged with `[engine_source=template]` without crashing.

### Are LLM settings hardcoded?
**No.** All LLM settings are fully configurable through standard environment variables in `.env`.

### OpenAI-Compatible Endpoint Support
QuantizedAlert natively connects to **any OpenAI-compatible API endpoint** using standard variables:

| Variable | Description | Default |
|---|---|---|
| `OPENAI_MODEL` | Model name / ID | *(empty = uses template prose)* |
| `OPENAI_API_KEY` | API Key for the endpoint | `sk-no-key-required` (if unset) |
| `OPENAI_BASE_URL` | Base URL of the OpenAI-compatible endpoint | `https://api.openai.com/v1` |

*(Note: Aliases `QUANTIZEDALERT_LLM_MODEL`, `QUANTIZEDALERT_LLM_API_KEY`, `QUANTIZEDALERT_LLM_BASE_URL`, and legacy `UNLOCKAID_LLM_*` are also supported).*

#### Provider Configuration Examples in `.env`:

**1. Official OpenAI:**
```bash
OPENAI_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://api.openai.com/v1
```

**2. DeepSeek API:**
```bash
OPENAI_MODEL=deepseek-chat
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://api.deepseek.com/v1
```

**3. Local Ollama (Zero cost, offline):**
```bash
OPENAI_MODEL=llama3.1:8b
OPENAI_API_KEY=ollama
OPENAI_BASE_URL=http://localhost:11434/v1
```

**4. Local vLLM / LocalAI / SGLang:**
```bash
OPENAI_MODEL=qwen2.5-coder
OPENAI_API_KEY=none
OPENAI_BASE_URL=http://localhost:8000/v1
```

**5. OpenRouter:**
```bash
OPENAI_MODEL=meta-llama/llama-3.1-8b-instruct
OPENAI_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://openrouter.ai/api/v1
```

---

## 2. Component Repositories & Required Tree Structure

QuantizedAlert orchestrates two external Class-1 assets plus market data:

1. **`quantizedalert`** (this repo): Core quant orchestrator, CLI, SQLite WAL database, alert intelligence, dashboard.
2. **`qlib`** (external repo): Microsoft's quantitative research engine (`github.com/microsoft/qlib`).
3. **`daily_stock_analysis`** (DSA, external repo): Notification delivery service (`NotificationService`) supporting 14 push channels (Telegram, Slack, Discord, Email, Feishu, Webhooks).
4. **`qlib_data`** (market data): Daily binary dump for CSI300 (A-share data).

### Do the sibling repositories require LLM variables?
- **`qlib`**: **NO.** It is a pure C++/Python machine learning and backtesting engine. No LLM variables.
- **`daily_stock_analysis`**: **NO** (when driven by QuantizedAlert). While DSA standalone includes an LLM analyzer, QuantizedAlert **only** uses DSA's `NotificationService` for dispatching alerts to configured channels. It only needs alert channel tokens (e.g. `TELEGRAM_BOT_TOKEN`, `SLACK_WEBHOOK_URL`, `CUSTOM_WEBHOOK_URLS`), not LLM keys.

---

### Recommended Filesystem Layout

On your target Linux box (e.g. under `/root` or `/home/<user>/workspace`):

```text
<base_dir>/
├── repos/
│   ├── qlib/                       # Git clone of Microsoft Qlib
│   └── daily_stock_analysis/       # Git clone of Daily Stock Analysis
│
└── work/                           # (or any project directory)
    └── unlockaid/                  # Project repository directory
        ├── .env                    # Environment file (from .env.example)
        ├── .venv/                  # Python 3.11 virtual environment
        ├── alembic/                # Database migrations
        ├── config/
        │   ├── platform.yaml       # Platform asset paths
        │   └── workspaces/         # Workspace configs (demo.yaml, etc.)
        ├── data/
        │   ├── quantizedalert.db   # SQLite database (auto-created)
        │   ├── artifacts/          # Trained models, metrics, backtests
        │   └── backups/            # Database backups
        ├── repos/                  # Symlinks to <base_dir>/repos (or relative paths)
        │   ├── qlib -> ../../repos/qlib
        │   └── daily_stock_analysis -> ../../repos/daily_stock_analysis
        ├── scripts/                # Utility and smoke test scripts
        └── src/quantizedalert/     # Core Python package
```

*(Note: Market data dump defaults to `~/.qlib/qlib_data/cn_data` or can be overridden via `QUANTIZEDALERT_QLIB_URI` in `.env`)*.

---

## 3. Step-by-Step Migration & Setup (Copy to New Box)

### Step 1 — OS Prerequisites (Ubuntu/Debian)

Install Python 3.11, build tools, and system dependencies:

```bash
sudo apt-get update && sudo apt-get install -y \
  build-essential \
  git \
  curl \
  wget \
  gzip \
  tar \
  python3.11 \
  python3.11-venv \
  python3.11-dev
```

*(Optional but recommended: install `uv` for ultra-fast package management)*:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

---

### Step 2 — Directory Setup & Repository Cloning / Copying

Set up the directory structure:

```bash
# Define your base workspace directory
export BASE_DIR=/root   # or /home/ubuntu
mkdir -p $BASE_DIR/repos $BASE_DIR/work

# 1. Clone or copy Microsoft Qlib
cd $BASE_DIR/repos
git clone https://github.com/microsoft/qlib.git qlib

# 2. Clone or copy Daily Stock Analysis (DSA)
cd $BASE_DIR/repos
git clone https://github.com/mizikakao/daily_stock_analysis.git daily_stock_analysis
# (or rsync your local copy: rsync -avz /source/daily_stock_analysis/ $BASE_DIR/repos/daily_stock_analysis/)

# 3. Copy or clone QuantizedAlert
cd $BASE_DIR/work
# rsync -avz --exclude '.venv' --exclude '__pycache__' --exclude '.git' /source/unlockaid/ $BASE_DIR/work/unlockaid/
# or git clone <your-repo-url> unlockaid
```

In the project directory, set up the convenience symlinks pointing to sibling repos:
```bash
cd $BASE_DIR/work/unlockaid
mkdir -p repos
ln -sfn $BASE_DIR/repos/qlib repos/qlib
ln -sfn $BASE_DIR/repos/daily_stock_analysis repos/daily_stock_analysis
```

---

### Step 3 — Python Virtual Environment & Dependency Installation

Create a Python 3.11 virtual environment and install exact dependencies:

```bash
cd $BASE_DIR/work/unlockaid

# Create virtual environment with Python 3.11
python3.11 -m venv .venv
source .venv/bin/activate

# Upgrade pip & packaging tools
pip install --upgrade pip setuptools wheel

# Install locked dependencies
pip install -r requirements.lock

# Install qlib in editable mode into the virtual environment
pip install -e $BASE_DIR/repos/qlib

# Install quantizedalert in editable mode
pip install -e .
```

---

### Step 4 — Fetch / Copy Market Data Dump

QuantizedAlert runs on CSI300 market data. You have two options:

#### Option A: Automatic download using QuantizedAlert CLI
```bash
cd $BASE_DIR/work/unlockaid
.venv/bin/quantizedalert data refresh
```
This automatically downloads the official open qlib binary dump into `~/.qlib/qlib_data/cn_data`.

#### Option B: Direct copy from your source machine
```bash
mkdir -p ~/.qlib/qlib_data
rsync -avz /source/qlib_data/cn_data/ ~/.qlib/qlib_data/cn_data/
```

---

### Step 5 — Configure Environment (`.env`)

Copy the environment template:

```bash
cd $BASE_DIR/work/unlockaid
cp .env.example .env
```

Edit `.env`:
```bash
# Base paths
QUANTIZEDALERT_QLIB_URI=~/.qlib/qlib_data/cn_data
DSA_PATH=./repos/daily_stock_analysis
QLIB_PATH=./repos/qlib

# Server port & log level
QUANTIZEDALERT_PORT=8765
QUANTIZEDALERT_LOG=INFO
QUANTIZEDALERT_DRY_RUN=0

# Optional Dashboard token (leave blank for open dev mode)
QUANTIZEDALERT_DASHBOARD_TOKEN=

# OpenAI-Compatible LLM (Optional — leave blank for deterministic template mode)
OPENAI_MODEL=
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1

# Alert channels (Optional — configure as needed)
# CUSTOM_WEBHOOK_URLS=https://webhook.site/xxx
# TELEGRAM_BOT_TOKEN=
# TELEGRAM_CHAT_ID=
```

---

### Step 6 — Initialize Database and Workspaces

Run database migrations and set up sample workspaces:

```bash
cd $BASE_DIR/work/unlockaid

# 1. Apply Alembic baseline database migrations
.venv/bin/alembic upgrade head

# 2. Set up workspace configuration files from examples if not already present
for ws in demo ridge e2ev; do
  if [ ! -f "config/workspaces/${ws}.yaml" ] && [ -f "config/workspaces/${ws}.yaml.example" ]; then
    cp "config/workspaces/${ws}.yaml.example" "config/workspaces/${ws}.yaml"
  fi
done
```

---

## 4. Verification & Testing (Run This Last)

Run the verification sequence to prove that everything is operational:

### 1. Run Automated CI Suite
```bash
make ci
# Expected: ruff check passes with 0 errors, pytest passes 44 tests.
```

### 2. Run Qlib Integration Smoke Test
```bash
.venv/bin/python scripts/asset_smoke_qlib.py
# Expected output:
#   D.features OK ...
#   LGBModel train OK ...
#   backtest OK ...
#   SMOKE_OK total ...s
```

### 3. Run Full End-to-End Quant Loop
```bash
.venv/bin/quantizedalert e2e e2ev --force
# Expected output:
#   [1/4] research+validate: mdl_... passed=True ic=... IR=...
#   [2/4] deployed + daily inference: 300 predictions, ok=True
#   [3/4] alerts: ... delivered
#   [4/4] dashboard payload exported: data/exports/e2e_e2ev.json
#   E2E_OK
```

### 4. Verify LLM Explanation Polish
```bash
# Extract model ID from the latest run
MODEL_ID=$(sqlite3 data/quantizedalert.db "SELECT model_id FROM models ORDER BY created_at DESC LIMIT 1;")

# Run explanation agent
.venv/bin/quantizedalert explain e2ev $MODEL_ID
# If no LLM configured: outputs exact template summary with [engine_source=template]
# If LLM configured: outputs polished explanation using your configured OpenAI-compatible endpoint
```

### 5. Launch Web Dashboard
```bash
.venv/bin/quantizedalert serve --port 8765
# Open browser at http://localhost:8765
```

---

## 5. Summary Checklist for Moving to a New Machine

- [ ] Installed Python 3.11 and build tools (`build-essential`).
- [ ] Cloned/copied `qlib` to `$BASE_DIR/repos/qlib`.
- [ ] Cloned/copied `daily_stock_analysis` to `$BASE_DIR/repos/daily_stock_analysis`.
- [ ] Copied project repository to `$BASE_DIR/work/unlockaid`.
- [ ] Created Python 3.11 virtualenv `.venv` and installed `requirements.lock`.
- [ ] Installed `qlib` editable via `pip install -e ../../repos/qlib`.
- [ ] Market data downloaded or copied to `~/.qlib/qlib_data/cn_data`.
- [ ] Created `.env` with OpenAI-compatible endpoint variables (or left blank for template mode).
- [ ] Executed `alembic upgrade head`.
- [ ] Verified with `make ci` and `.venv/bin/quantizedalert e2e e2ev --force`.

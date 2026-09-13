# QuantizedAlert — Architecture, Operation & Cloud Migration Guide

This document provides a comprehensive breakdown of what **QuantizedAlert** does, how it works under the hood, how stock research and discovery operate, and how to migrate the entire system to a cloud environment (AWS, GCP, Azure, DigitalOcean, or private Linux servers).

---

## 1. What This Project Is & How It Works

### The Core Mission
**QuantizedAlert** is an autonomous, always-on quantitative research, model deployment, portfolio monitoring, and multi-channel alerting system.

In traditional finance, quantitative researchers develop predictive models, but operationalizing them requires separate schedulers, data pipelines, model registries, monitoring systems, and notification infrastructure. QuantizedAlert bridges this gap: it packages the entire quant lifecycle behind a single automated pipeline, integrating two proven open-source engines:
1. **Microsoft Qlib** (`repos/qlib`): Quantitative modeling engine handling market data, 158 alpha factors (Alpha158), machine learning models (LightGBM, Ridge, Lasso), walk-forward validation, and historical backtesting (`TopkDropoutStrategy`).
2. **Daily Stock Analysis (DSA)** (`repos/daily_stock_analysis`): Production-grade notification engine supporting 14 delivery channels (Telegram, Slack, Discord, Email, Feishu, WeCom, DingTalk, Pushover, ntfy, Gotify, PushPlus, ServerChan3, AstrBot, and custom webhooks).

---

### Architectural Flow (Layer-by-Layer)

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                          1. DATA LAYER (A)                              │
│  Downloads daily-bar market dumps, verifies freshness, checks anomalies │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        2. RESEARCH ENGINE (B)                           │
│  Alpha158 factor handler -> Trains ML models (LightGBM/Ridge) -> Backtest│
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  3. VALIDATION & MODEL REGISTRY (C, D)                  │
│  Walk-forward validation, overfit audit, information ratio (IR) gates   │
│  Stores passed models in SQLite with experiment lineage                 │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                   4. SCHEDULER & DEPLOYMENT (E)                         │
│  APScheduler daily cron (17:30 China Standard Time / market close)      │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     5. DAILY INFERENCE & SIGNALS (F)                    │
│  Pulls latest bars -> Predicts forward return -> Ranks entire universe   │
│  Detects large rank changes, portfolio risk, and model score drift      │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     6. ALERT INTELLIGENCE (G)                           │
│  Multi-factor score: severity, novelty, confidence, portfolio relevance  │
│  Applies deduplication, quiet hours, daily budget -> Dispatches via DSA │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     7. DASHBOARD & REST API (H)                         │
│  FastAPI + Jinja web dashboard: models, scorecard, runs, alerts         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Does It Research Stocks Itself or Do You Have to?

**It can do both, and by default it completely researches, analyzes, and ranks stocks itself across an entire market index without you needing to feed it individual stocks.**

Here is the exact breakdown of how research and discovery operate:

### Mode 1: Automated Market Universe Mode (Default & Primary)
- **You specify a market universe** (e.g. `universe: csi300` or `csi500`).
- **You do NOT need to feed it stocks.**
- QuantizedAlert queries Qlib to automatically pull the complete constituent list (e.g. all 300 stocks in China's CSI 300 index).
- For all 300 stocks, it:
  1. Computes 158 mathematical price-volume alpha factors (momentum, mean reversion, volatility, moving average ratios, liquidity indicators).
  2. Runs them through the trained machine learning model.
  3. Predicts expected forward excess returns.
  4. **Ranks every single stock in the entire universe from 1 to 300**.
  5. Monitors rank shifts: if an unmonitored stock jumps significantly (e.g. climbs 25 ranks into the top tier), QuantizedAlert automatically flags it and triggers an alert.

### Mode 2: Custom Baskets (User-Fed Stocks)
- If you leave `universe` empty and set `instruments: [SH600519, SZ000001, SH601318, ...]`, the system restricts data fetching, factor engineering, model training, and daily inference strictly to your chosen basket.

### Mode 3: Hybrid Universe with Watchlist / Portfolio Overlay (Recommended)
- You configure a broad universe (e.g. `universe: csi300`), but also supply:
  - `watchlist`: Specific stocks you want to monitor closely.
  - `portfolio`: Stocks you currently hold, along with their weights.
- The system evaluates and ranks the entire 300-stock index, but applies **elevated alert weighting** (`portfolio_relevance`) to your held assets. If a stock in your portfolio slips down the rankings or an anomaly is detected on a stock you hold, high-severity alerts are immediately routed to your channels.

### Mode 4: Factor Discovery Agent (`quantizedalert discover`)
- You can run the autonomous `FactorDiscoveryAgent` over any date window:
  ```bash
  quantizedalert discover demo --start 2025-06-01 --end 2026-06-01
  ```
- It computes single-factor Information Coefficients (IC) across market data to identify which alpha factors are generating the strongest predictive signal in the current market environment.

## 3. Advanced Intelligent Enhancements (US Equities, Discovery & Paper Execution)

QuantizedAlert incorporates advanced components from the quantitative trading ecosystem to support US equities, multi-factor conviction gating, and closed-loop paper execution:

### Stage 1: US Equities & Sector Intelligence Expansion (`quantizedalert.market`)
- **11 S&P 500 GICS Sector Coverage**: Evaluates XLK, XLF, XLV, XLY, XLP, XLE, XLI, XLB, XLU, XLRE, and XLC.
- **Momentum & Valuation Tracking**: Analyzes 1M, 3M, 6M returns relative to the `SPY` benchmark, RSI-14, and moving average alignment (SMA-50 / SMA-200) to assign a 0–100 sector rating and direction bias (`LONG`, `SHORT`, `NEUTRAL`).
- **Rate-Limited Data Fetching**: `RateLimiter` ensures requests to Yahoo Finance stay under 1 call per 0.6s with in-memory TTL caching (60s prices, 300s bars).
- **Turnkey Workspaces**: `config/workspaces/sp500.yaml` and `config/workspaces/us_tech.yaml` targeting US mega-caps and AI leaders.
- **CLI Inspection**: Run `quantizedalert sectors` to view live ratings and momentum across all 11 sectors.

### Stage 2: SimplyWallSt Discovery & Multi-Factor Conviction Gating (`quantizedalert.discovery`)
- **SimplyWallSt GraphQL Crawler**: Connects directly to `https://simplywall.st/graphql` using browser headers to query curated investment ideas (Undiscovered Gems, Value Cash Flows, Solid Balance Sheet, High Growth Tech & AI, AI Small Caps, High Insider Buying).
- **Offline Cache Fallback**: Seamlessly loads candidates from `market_cache/simplywallst/candidates.json` if offline.
- **SEC Fundamentals & Insider Scoring**: Evaluates revenue growth, net margin, debt/equity, current ratio, and ROE to classify companies into `STRONG`, `MODERATE`, or `WEAK`, alongside executive insider purchasing intensity.
- **4-Pillar Conviction Gating**:
  $$\text{Conviction Score} = 0.40 \cdot \text{Quant} + 0.30 \cdot \text{Fundamentals} + 0.20 \cdot \text{Insider} + 0.10 \cdot \text{Sector}$$
  Only alerts with conviction $\ge 65.0$ pass gating, eliminating noisy alerts and false positives before DSA dispatch.

### Stage 3: Closed-Loop Paper Trading & Shadow Regret (`quantizedalert.execution` & `quantizedalert.learning`)
- **Paper Trading Engine**: Realistically simulates market and limit orders with customizable slippage (default 5 bps) and half-spread modeling. Tracks cash balance, position cost averaging, market value, and realized PnL.
- **Automated Alert Execution**: High-conviction alerts automatically trigger paper trade execution with configurable portfolio sizing (e.g. 5% equity allocation).
- **Shadow Regret Self-Improvement Loop**:
  - Evaluates every generated signal against subsequent market price changes.
  - **Type I Regret (False Positive)**: Alert delivered $\to$ trade lost money or lagged benchmark.
  - **Type II Regret (False Negative)**: Signal suppressed $\to$ stock rallied $\ge 3\%$.
  - **Adaptive Threshold Tuning**: Recommends dynamic conviction threshold adjustments based on rolling false-positive and false-negative rates to continuously optimize signal quality.

---

## 4. LLM Usage & Natural Language Polish

### Does this project rely on LLMs to predict stocks?
**No.** All quant computations are **100% deterministic**:
- Factor extraction (Alpha158), model training (LightGBM, Ridge, Lasso), predictions, backtests, walk-forward folds, Sharpe, Information Ratio (IR), and max drawdown are executed via numerical Python and C++ (`qlib`, `numpy`, `pandas`, `scipy`).
- QuantizedAlert adheres to a strict **anti-quack principle**: LLMs **never** predict stock returns, generate trading signals, or fabricate numbers.

### Where LLMs Are Used
LLMs are used **only** in `ResearchExplanationAgent` (invoked via `quantizedalert explain <workspace> <model>`). It translates backtest metrics and overfit audits into plain English for stakeholders.

### Fallback Guarantee
If no LLM endpoint or API key is provided, the system seamlessly outputs deterministic template prose marked `[engine_source=template]` without error.

### OpenAI-Compatible Endpoint Support
QuantizedAlert supports any OpenAI-compatible provider:
```bash
# In .env:
OPENAI_MODEL=deepseek-chat           # or gpt-4o-mini, llama3.1:8b, qwen2.5-coder
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx   # API key (or 'ollama' / 'none' for local)
OPENAI_BASE_URL=https://api.deepseek.com/v1  # or http://localhost:11434/v1
```

---

## 4. Cloud Migration Guide

When migrating QuantizedAlert from this machine to the cloud, follow these instructions.

### What Needs to Be Copied vs Excluded

| Path / Asset | Action | Reason |
|---|---|---|
| `src/quantizedalert/` | **Copy** | Core application package |
| `src/unlockaid/` | **Copy** | Backward-compatibility shim |
| `alembic/` & `alembic.ini` | **Copy** | Database schema migrations |
| `config/platform.yaml` | **Copy** | Platform runtime configuration |
| `config/workspaces/` | **Copy** | Workspace configurations (YAMLs) |
| `scripts/` | **Copy** | Smoke tests, verification scripts, DB backup helper |
| `pyproject.toml` | **Copy** | Package definition & dependencies |
| `requirements.lock` | **Copy** | Pinned dependencies lockfile |
| `Makefile` | **Copy** | Build & test shortcuts |
| `docs/` | **Copy** | Architecture and reference docs |
| `.env.example` | **Copy** | Template environment configuration |
| `data/artifacts/` | **Optional** | Pre-trained models (copy if you want to keep existing models) |
| `data/quantizedalert.db` | **Optional** | SQLite database (copy if you want to preserve history) |
| `.venv/` | **EXCLUDE** | Host-specific compiled Python binaries and C-extensions |
| `__pycache__/` | **EXCLUDE** | Host-specific bytecode cache |
| `.pytest_cache/`, `.ruff_cache/` | **EXCLUDE** | Local cache files |
| `.git/` | **EXCLUDE / Re-clone** | Not needed if copying source snapshot |

---

### Cloud Filesystem Tree Structure

On your cloud instance (e.g. `/root` or `/home/ubuntu`):

```text
<base_dir>/
├── repos/
│   ├── qlib/                       # Clone of github.com/microsoft/qlib
│   └── daily_stock_analysis/       # Clone of github.com/mizikakao/daily_stock_analysis
│
└── work/
    └── quantizedalert/             # QuantizedAlert repository root
        ├── .env                    # Cloud environment variables (from .env.example)
        ├── .venv/                  # Fresh virtualenv built on cloud host
        ├── alembic/                # Migration scripts
        ├── alembic.ini             # Alembic configuration
        ├── config/
        │   ├── platform.yaml       # Portable path configuration
        │   └── workspaces/         # Workspace configs (demo.yaml, etc.)
        ├── data/
        │   ├── quantizedalert.db   # Production SQLite DB (or mounted volume)
        │   ├── artifacts/          # Model artifacts & MLflow runs
        │   ├── backups/            # Scheduled DB backups
        │   └── exports/            # E2E JSON exports
        ├── repos/                  # Symlinks to <base_dir>/repos
        │   ├── qlib -> ../../repos/qlib
        │   └── daily_stock_analysis -> ../../repos/daily_stock_analysis
        ├── scripts/                # Verification & smoke test scripts
        └── src/                    # Python package source code
```

---

### Step-by-Step Cloud Setup Commands

#### Step 1: Prepare the Cloud Host (Ubuntu 20.04 / 22.04 / 24.04 — x86_64 or ARM64 / aarch64)
SSH into your cloud server (e.g. `ubuntu@150.136.72.148`) and install essential build tools:
```bash
sudo apt-get update && sudo apt-get install -y \
  build-essential \
  git curl wget gzip tar \
  libgomp1 sqlite3 rsync
```

**Install `uv` (Ultra-fast Python package manager) and standalone Python 3.11:**
```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# Install standalone CPython 3.11 on any Linux architecture (x86_64 or ARM64):
~/.local/bin/uv python install 3.11
```

#### Step 2: Set Up Directories and Sibling Repositories
```bash
export BASE_DIR=/home/ubuntu   # or /root
mkdir -p $BASE_DIR/repos $BASE_DIR/quantizedalert

# 1. Clone Microsoft Qlib
cd $BASE_DIR/repos
git clone https://github.com/microsoft/qlib.git qlib

# 2. Clone Daily Stock Analysis (DSA)
cd $BASE_DIR/repos
git clone https://github.com/mizikakao/daily_stock_analysis.git daily_stock_analysis
```

#### Step 3: Copy QuantizedAlert from Local Host to Cloud
From your local development machine, transfer the project files and market data:
```bash
# 1. Transfer QuantizedAlert codebase
rsync -avz --progress \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  /root/work/quantizedalert/ user@<cloud-ip>:$BASE_DIR/quantizedalert/

# 2. Transfer Sibling Repositories (if pre-configured)
rsync -avz --progress \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  /root/repos/ user@<cloud-ip>:$BASE_DIR/repos/

# 3. Transfer Qlib Market Binary Data (avoids re-downloading ~1.4GB over slow lines)
rsync -avz --progress \
  /root/.qlib/qlib_data/ user@<cloud-ip>:~/.qlib/qlib_data/
```

#### Step 4: Configure Symlinks and Virtual Environment
On the cloud host:
```bash
cd $BASE_DIR/quantizedalert

# Create convenience symlinks to sibling repos
mkdir -p repos
ln -sfn $BASE_DIR/repos/qlib repos/qlib
ln -sfn $BASE_DIR/repos/daily_stock_analysis repos/daily_stock_analysis

# Create Python 3.11 virtual environment using uv
~/.local/bin/uv venv .venv --python 3.11

# Install Qlib into the virtualenv (editable)
~/.local/bin/uv pip install --python .venv/bin/python -e $BASE_DIR/repos/qlib

# Install QuantizedAlert with dev, billing, and LLM extras
~/.local/bin/uv pip install --python .venv/bin/python -e ".[dev,billing,llm]"
```

#### Step 5: Install Cloudflare Tunnel (`cloudflared`)
To securely access the QuantizedAlert dashboard and APIs without exposing public ports:
```bash
# For ARM64 / aarch64 (Oracle Cloud Ampere, etc.):
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i cloudflared.deb
rm cloudflared.deb

# (For x86_64 / amd64):
# curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
# sudo dpkg -i cloudflared.deb

# Verify installation (DO NOT START TUNNEL until configured):
cloudflared --version
```

**Configuring Cloudflare Tunnel (Run when ready):**
```bash
# 1. Login to Cloudflare
cloudflared tunnel login

# 2. Create the tunnel
cloudflared tunnel create quantizedalert

# 3. Configure ~/.cloudflared/config.yml:
cat <<EOF > ~/.cloudflared/config.yml
tunnel: <TUNNEL-UUID>
credentials-file: /home/ubuntu/.cloudflared/<TUNNEL-UUID>.json
ingress:
  - hostname: quant.yourdomain.com
    service: http://localhost:8765
  - service: http_status:404
EOF

# 4. Route DNS:
cloudflared tunnel route dns quantizedalert quant.yourdomain.com

# 5. Run tunnel (or install as system service):
# cloudflared tunnel run quantizedalert
# Or: sudo cloudflared service install
```

#### Step 6: Environment Configuration (`.env`)
> [!IMPORTANT]
> Always verify and update `.env` on the cloud server before starting the service. Set secure tokens and actual notification webhooks.

```bash
cd $BASE_DIR/quantizedalert
cp -n .env.example .env
nano .env
```
Key production variables to verify:
```bash
# Core paths
QUANTIZEDALERT_QLIB_URI=~/.qlib/qlib_data/cn_data
DSA_PATH=/home/ubuntu/repos/daily_stock_analysis
QLIB_PATH=/home/ubuntu/repos/qlib

# Server & logging
QUANTIZEDALERT_PORT=8765
QUANTIZEDALERT_LOG=INFO
QUANTIZEDALERT_DRY_RUN=0

# Security: Set a secure dashboard API token
QUANTIZEDALERT_DASHBOARD_TOKEN=your_secure_random_token_here

# Notification Channels (set at least one for real alert delivery)
CUSTOM_WEBHOOK_URLS=https://your-webhook-endpoint.com/alerts
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
SLACK_WEBHOOK_URL=
```

#### Step 7: Database Migration
Execute Alembic database migrations to initialize or upgrade the SQLite schema:
```bash
cd $BASE_DIR/quantizedalert
.venv/bin/alembic upgrade head
```

---

### Step 8: Production Deployment Options

#### Option A: Native Systemd Service (Recommended for dedicated VM)

Create `/etc/systemd/system/quantizedalert.service`:
```bash
sudo tee /etc/systemd/system/quantizedalert.service > /dev/null <<EOF
[Unit]
Description=QuantizedAlert Autonomous Quant Research & Alerting Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/quantizedalert
EnvironmentFile=/home/ubuntu/quantizedalert/.env
ExecStart=/home/ubuntu/quantizedalert/.venv/bin/quantizedalert serve --host 0.0.0.0 --port 8765 --cron
Restart=always
RestartSec=10
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable service:
sudo systemctl daemon-reload
sudo systemctl enable quantizedalert

# Start only after .env is verified:
# sudo systemctl start quantizedalert
```

#### Option B: Docker Compose Deployment

QuantizedAlert includes a containerized deployment setup:
```bash
cd $BASE_DIR/quantizedalert

# Build and run with docker compose (mounts persistent data and models):
docker compose build
docker compose up -d

# Check container logs:
docker compose logs -f
```

---

## 5. End-to-End Verification on Cloud

After deploying to the cloud host, run this verification sequence:

```bash
cd $BASE_DIR/work/quantizedalert

# 1. Run full test suite (must pass 44/44 tests)
make ci

# 2. Run standalone Qlib smoke test
QUANTIZEDALERT_ALLOW_STALE=1 .venv/bin/python scripts/asset_smoke_qlib.py

# 3. Run full E2E loop (train -> validate -> deploy -> inference -> alert dispatch)
QUANTIZEDALERT_ALLOW_STALE=1 .venv/bin/quantizedalert e2e e2ev --force

# 4. Check that E2E payload was exported
cat data/exports/e2e_e2ev.json | head -n 30

# 5. Access the Web Dashboard
curl -s http://localhost:8765/ | head -n 20
```

---

## 6. Cloud Migration Checklist

- [ ] Installed Python 3.11 and build essentials on cloud VM.
- [ ] Cloned `qlib` and `daily_stock_analysis` to `$BASE_DIR/repos/`.
- [ ] Rsynced project source to `$BASE_DIR/work/quantizedalert/` (excluding `.venv`, `__pycache__`, `.git`).
- [ ] Created `.venv` and installed dependencies via `uv pip install -e ".[dev]"`.
- [ ] Downloaded market data via `.venv/bin/quantizedalert data refresh`.
- [ ] Configured `.env` with paths, security tokens, and alert channel webhooks.
- [ ] Ran database migration: `.venv/bin/alembic upgrade head`.
- [ ] Verified installation with `make ci` and `quantizedalert e2e e2ev`.
- [ ] Enabled systemd daemon (`quantizedalert.service`) for scheduled daily runs.

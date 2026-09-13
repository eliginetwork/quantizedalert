# QuantizedAlert

**Turn quantitative research into an always-on research and portfolio
monitoring system.**

QuantizedAlert operationalizes the research→production gap: it composes two proven
open engines — **Qlib** (`/root/repos/qlib`, research/backtest engine, editable
install) and **daily_stock_analysis** (`/root/repos/daily_stock_analysis`,
14-channel notification engine) — behind one product loop:

    choose universe → research → backtest → validate → deploy → monitor → alert

Customers pay to stop maintaining schedulers, data pipelines, model registries
and alert plumbing — **your quant infrastructure, managed for you** — not
"hosted Qlib", and not "an AI that predicts stocks".

---

## 1. Requirements

| thing | version / note |
|---|---|
| Python | **3.11** (3.12+ may break qlib wheels) |
| RAM | ≥ 8 GB free for Alpha158 feature build (CSI300, ~2.5 years) |
| Disk | ~600 MB for the qlib cn data dump + ~200 MB artifacts |
| Asset repos | qlib and daily_stock_analysis checked out (paths configurable, see §3) |
| OS libs | none beyond a normal Python stack; qlib wheels bundle RocksDB |

## 2. Install (one-time, from this directory)

```bash
cd /root/work/quantizedalert

# 1) virtualenv
uv venv .venv --python 3.11          # or: python3.11 -m venv .venv

# 2) the two Class-1 assets, editable, into the SAME venv
uv pip install --python .venv/bin/python -e /root/repos/qlib
#    DSA needs its own dep set (its senders read env config at runtime):
uv pip install --python .venv/bin/python requests "pandas>=2.1,<3" python-dotenv

# 3) quantizedalert itself (+ dev extras for tests)
uv pip install --python .venv/bin/python -e ".[dev]"
#    optional: billing + LLM polish
uv pip install --python .venv/bin/python stripe litellm

# 4) sanity
.venv/bin/quantizedalert --version        # quantizedalert 0.1.0
```

## 3. Configure

Platform config: `config/platform.yaml` (paths default to this layout):

```yaml
qlib_provider_uri: ~/.qlib/qlib_data/cn_data   # env override: QUANTIZEDALERT_QLIB_URI
qlib_region: cn
dsa_path: ./repos/daily_stock_analysis     # env override: DSA_PATH
qlib_path: ./repos/qlib                    # env override: QLIB_PATH
db_path: data/quantizedalert.db
artifact_dir: data/artifacts
workspace_dir: config/workspaces
data_dir: data
train_n_jobs: 8
num_boost_round: 200
```

Workspace (customer) config: created by `quantizedalert init-workspace` into
`config/workspaces/<ws>.yaml` — universe, watchlist/portfolio, model +
hyperparameters, backtest params, schedule time, alert prefs (channels, budget,
quiet hours, thresholds), plan.

## 4. Acquire data (Layer A)

```bash
.venv/bin/quantizedalert data refresh      # downloads ~564 MB qlib cn daily-bar dump
                                           # (chenditc/investment_data, open-licensed)
.venv/bin/quantizedalert data health demo  # freshness / stale / anomaly / missing check
```

## 5. Alert channel setup (Layer G)

Channels are DSA's — configure with **DSA's standard env contract** (read at
process start), then point the workspace at the channel slugs:

| channel slug | env var(s) (set before `daily`/`alert-test`/`serve`) |
|---|---|
| `custom_webhook` | `CUSTOM_WEBHOOK_URLS=https://hook.example/x` (comma-separated) |
| `telegram` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| `slack` | `SLACK_WEBHOOK_URL` |
| `discord` | `DISCORD_WEBHOOK_URL` |
| `email` | `MAIL_SENDER`, `MAIL_PASSWORD`, `MAIL_RECEIVERS` (SMTP host inferred from sender domain) |
| `feishu` | `FEISHU_WEBHOOK_URL` (+ optional secret/keyword) |
| `wecom` | `WECHAT_WEBHOOK_URL` |
| `dingtalk` | `DINGTALK_WEBHOOK_URL` + `DINGTALK_SECRET` |
| `pushover` / `ntfy` / `gotify` / `pushplus` / `serverchan3` / `astrbot` | see DSA `.env.example` |

Prove delivery:

```bash
.venv/bin/quantizedalert init-workspace demo --channels custom_webhook,telegram
CUSTOM_WEBHOOK_URLS=https://hook.example/x .venv/bin/quantizedalert alert-test demo
```

No real endpoint handy? Minimal POST-recording sink (plain `http.server` answers
501 to POST — don't use it):

```bash
python - <<'PY' &
from http.server import BaseHTTPRequestHandler, HTTPServer
class S(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('content-length', 0))
        open('/tmp/quantizedalert-alerts.jsonl','ab').write(self.rfile.read(n) + b'\n')
        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
HTTPServer(('127.0.0.1', 8921), S).serve_forever()
PY
export CUSTOM_WEBHOOK_URLS=http://127.0.0.1:8921/hook
tail -f /tmp/quantizedalert-alerts.jsonl
```

## 6. Environment variables (QuantizedAlert-specific)

Copy env template:
```bash
cp .env.example .env   # then edit .env with real values
```

| var | effect |
|---|---|
| `QUANTIZEDALERT_QLIB_URI` | override provider path (legacy `UNLOCKAID_QLIB_URI` also supported) |
| `QLIB_PATH` / `DSA_PATH` | asset repo locations |
| `QUANTIZEDALERT_PORT` | dashboard port (default 8765) |
| `QUANTIZEDALERT_LOG` | log level (default INFO) |
| `QUANTIZEDALERT_DRY_RUN=1` | alert dispatch records sends, skips network |
| `OPENAI_MODEL` / `QUANTIZEDALERT_LLM_MODEL` | model id for explanation polish (unset = template prose; fallback is always tagged) |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `QUANTIZEDALERT_STRIPE_PRICES` | billing adapter (lazy import; app runs fine unset) |
| `MLFLOW_DISABLE_AGENT_HINT=1` | silence mlflow log noise (qlib uses mlflow recorders) |

## 7. Run the product

### 7a. Full MVP loop, one command (§12)

```bash
.venv/bin/quantizedalert e2e ridge    # train → backtest → validate → register →
                                      # deploy → daily inference → alerts (delivered)
                                      # → data/exports/e2e_ridge.json
# exits non-zero WITHOUT deploying if validation rejects the model (fail-safe §24)
# --force deploys anyway (explicit override)
```

### 7b. Step by step

```bash
.venv/bin/quantizedalert init-workspace demo --plan individual \
    --watchlist SH600519,SZ000001,SH601318,SH600036,SZ000333 \
    --channels custom_webhook --schedule 17:30 --email you@example.com

.venv/bin/quantizedalert research  demo               # train + qlib TopkDropout backtest
.venv/bin/quantizedalert validate  demo <model_id>    # gates + walk-forward + overfit audit
.venv/bin/quantizedalert deploy    demo <model_id>    # validated models only
.venv/bin/quantizedalert daily     demo               # inference → analytics → alerts
.venv/bin/quantizedalert daily     demo --asof 2026-09-03   # backfill a prior session day
```

### 7c. Autonomous research (§6 agents)

```bash
.venv/bin/quantizedalert discover    demo --start 2025-06-01 --end 2026-06-01
.venv/bin/quantizedalert experiments demo --max-runs 3       # quota-metered grid
.venv/bin/quantizedalert explain     demo <model_id>          # customer prose, exact numbers
```

### 7d. Dashboard + scheduler (Layers E+H)

```bash
.venv/bin/quantizedalert serve --cron            # http://127.0.0.1:8765
# --cron registers one APScheduler daily job per enabled deployment at its
# schedule_time (Asia/Shanghai), misfire grace 1 h; dashboard + scheduler in
# one process. Routes: /  /w/<ws>  /api/<ws>/summary|alerts|predictions|scorecard
```

### 7e. Ops / commercial views

```bash
.venv/bin/quantizedalert registry  [--workspace demo] [--model mdl_x]
.venv/bin/quantizedalert scorecard demo          # runs, alert gen/deliver/view, uptime
.venv/bin/quantizedalert economics demo          # per-customer contribution margin
```

## 8. Verify

```bash
.venv/bin/python -m pytest tests/ -q          # 44 tests, ~20 s (live tests included)
.venv/bin/python scripts/asset_smoke_qlib.py  # standalone qlib train/backtest proof
```

`tests/test_success_criteria.py` is the SC1–SC10 matrix: SC1 qlib executes
(train+backtest, lineage), SC2 **real DSA delivery through a live local webhook
sink**, SC4 fault injection on both Class-1 assets, SC8 overfit detection,
SC10 dashboard contract. Live tests skip cleanly without the data dump.

## 9. Architecture (layers A–H)

```
A data       quantizedalert/data        qlib dump refresh + per-instrument health
B research   quantizedalert/engine      qlib adapter (dataset/model/train/backtest/walk-forward)
             quantizedalert/research    runner: train → metrics → artifacts → registry
C validation quantizedalert/research    gates + expanding-window walk-forward + OverfitAuditAgent
D registry   quantizedalert/store       sqlite: models, dataset refs, recorder lineage
E deploy     quantizedalert/deploy      APScheduler cron per deployment, misfire grace
F daily      quantizedalert/analysis    inference on freshest segment, rank Δ, portfolio analytics
G alerting   quantizedalert/alerts      weighted scoring (severity/novelty/confidence/
                                        portfolio/risk/history) + budgets, quiet hours,
                                        dedup → DSA's 14 senders
H dashboard  quantizedalert/dashboard   FastAPI: what changed → assets → significance → context
§6 agents    quantizedalert/agents      discovery/experiment/backtest/overfit/monitoring/
                                        regime/risk/explanation — deterministic rules over
                                        real outputs; optional LLM prose polish, tagged
§9/22 comm.  quantizedalert/commercial  plans, quotas, metering, contribution margin, Stripe
```

## 10. Pricing

| plan | price | quotas |
|---|---|---|
| Free | $0 | 1 portfolio, 5 research, 30 inference/mo, 2 alerts/day |
| Individual | $49/portfolio/mo | 1 portfolio, 20 research, 200 inference, 5 alerts/day |
| Professional | $149–$499 | multiple portfolios/models, advanced monitoring |
| Team | $500–$2,000+ | seats, shared registry, permissions |
| Enterprise | custom | private deploy, SSO, audit, API |

Usage is metered per workspace at every pipeline step; `quantizedalert economics <ws>`
shows exact contribution margin from real metered usage (cost model calibrated
to this host; see `commercial/plans.py`).

## 11. Honest limits (read before trusting a number)

Community qlib dump only (A-share daily bars; survivorship/corporate actions at
the dump's mercy); 1d/5d horizons; v0.1 is single-tenant-per-process channel
config, **no auth** (days 31-60 per objective §13); validation ≠ profit
guarantee — the product's value is monitoring and explaining models *even when
they lose*. Full list: [docs/DEVIATIONS.md](docs/DEVIATIONS.md).

## 12. Troubleshooting

| symptom | cause / fix |
|---|---|
| `ModuleNotFoundError. CatBoostModel/XGBModel skipped` at startup | benign — qlib optional-model notices; install catboost/xgboost to enable those model types |
| qlib init fails / empty calendar | run `quantizedalert data refresh`; check `QUANTIZEDALERT_QLIB_URI` |
| alerts delivered: none on first day | first run has no previous day to diff — `daily <ws> --asof <prior session>` then re-run for the live day; check dedup window (24 h default) before alert-test spamming |
| webhook delivery false | sink not running / `CUSTOM_WEBHOOK_URLS` not set in the same shell (DSA reads env at process start); plain `http.server` replies 501 to POST — use a POST-logging sink |
| mlflow file-store errors during train | engine sets `MLFLOW_ALLOW_FILE_STORE=true` via `config.py`; only matters if you scrub env |
| `quota exceeded` | real plan limit — check `economics`, or init workspace `--plan individual` |
| dashboard 500 after code edits | stale server process — restart `serve`; config/store changes need the restart |
| port 8765 busy | `QUANTIZEDALERT_PORT=8899 quantizedalert serve` |
| slow research runs | `train_n_jobs` in platform.yaml; Alpha158 on CSI300 is CPU-heavy — 8 jobs ≈ 40 s/run on a Ryzen AI 9 |

## 13. Development

```bash
.venv/bin/python -m pytest tests/ -q                 # full suite (offline + live)
.venv/bin/quantizedalert e2e ridge                   # the live loop
# repo layout: src/quantizedalert/<layer>/, config/workspaces/*.yaml,
# data/(sqlite db + artifacts + exports), scripts/asset_smoke_qlib.py
```

Docs: [docs/PORTABILITY_AND_E2E_GUIDE.md](docs/PORTABILITY_AND_E2E_GUIDE.md) (architecture, cloud migration & E2E guide),
[docs/ASSET_INVENTORY.md](docs/ASSET_INVENTORY.md) (reuse-vs-own per capability),
[docs/OBJECTIVE_DECOMPOSITION.md](docs/OBJECTIVE_DECOMPOSITION.md),
[docs/BUILD_EVIDENCE.md](docs/BUILD_EVIDENCE.md) (claim→command→output),
[docs/DEVIATIONS.md](docs/DEVIATIONS.md), [docs/SELF_REVIEW.md](docs/SELF_REVIEW.md).


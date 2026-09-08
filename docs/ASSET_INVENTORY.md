# Asset Inventory — UnlockAid (Playbook Gate 1)

Every capability below was inspected in source and, where marked ✅, executed from
this project's environment (`/root/work/unlockaid/.venv`, Python 3.11.15).

---

## Asset 1: qlib — `/root/repos/qlib` (pyqlib 0.9.8.dev31, MIT)

**Class 1: Platform Runtime Engine — research & quantitative modeling engine.**

| # | Capability | Module path | Verified | Integration decision |
|---|---|---|---|---|
| 1 | Data layer: expression engine (`$close`, `Ref`, operators), calendars, instruments, binary column store | `qlib.data` (`D.features/D.calendar/D.instruments`), `qlib/data/ops.py`, `qlib/data/storage` | ✅ 207 real rows SH600519/SZ000001/SH601318 to 2026-09-04 | **USE** as-is; UnlockAid adds freshness/staleness/anomaly checks on top (Layer A) |
| 2 | Factor engineering: Alpha158/Alpha360 handler, processors (CSZScoreNorm, DropnaLabel), configurable factor expressions | `qlib.contrib.data.handler`, `qlib.contrib.data.loader`, `qlib.data.dataset.processor` | ✅ Alpha158 fit on csi300, 121,909 samples | **USE** as-is; UnlockAid factor-discovery agent generates expression lists fed into the handler config |
| 3 | Model zoo: 34 models incl. LGBModel, Linear, CatBoost, PyTorch family (LSTM/GRU/ALSTM/GATS/TFT/HIST/ADARNN…), unified `Model.fit(dataset)/predict()` | `qlib.contrib.model.*`, `qlib.model.base` | ✅ LGBModel trained; test IC=0.0142, 26,100 OOS samples | **USE** LGBModel + Linear for MVP; expose others via config |
| 4 | Backtesting: `backtest()` with TopkDropoutStrategy, SimulatorExecutor, exchange cost model, portfolio report (`return, bench, cost, turnover`), `risk_analysis` (annualized return, IR, max drawdown) | `qlib.backtest`, `qlib.contrib.strategy`, `qlib.contrib.evaluate` | ✅ backtest ran; excess ann.return=32.27%, IR=1.67, maxdd=-6.60% | **USE** as-is; UnlockAid standardizes report schema |
| 5 | Experiment management: mlflow-backed Experiment/Recorder, `SignalRecord`, `SigAnaRecord` (IC/ICIR/rank IC), `PortAnaRecord` | `qlib.workflow`, `qlib.workflow.record_temp` | ✅ (Recorder exercised through LGBModel fit path) | **USE**; UnlockAid registry stores recorder IDs for lineage |
| 6 | Daily inference / online serving: `OnlineStrategy`, `RollingStrategy`, `PredUpdater`, `RMDLoader` | `qlib.workflow.online`, `qlib.contrib.online` | source-inspected; covered by MVP daily path via direct model.predict | **WRAP**: UnlockAid scheduler drives qlib predict daily |
| 7 | Rolling retrain: `Rolling` workflows for model refresh | `qlib.contrib.rolling.base` | source-inspected | **USE later** (MVP exposes retrain trigger; full rolling = post-MVP) |
| 8 | Portfolio optimization: cvxpy-based optimizer, order execution RL (`qlib.rl`) | `qlib.contrib.strategy`, `qlib.rl` | source-inspected | **DEFER** to Portfolio Intelligence expansion (§16); MVP uses TopkDropout |

**Environment facts:** installed editable; needs `MLFLOW_ALLOW_FILE_STORE=true` or sqlite URI
(mlflow 3.x deprecates file store — UnlockAid pins sqlite tracking URI in production, see DEVIATIONS).
`LABEL0` is the label column; Alpha158 label = `Ref($close,-2)/Ref($close,-1)-1`.

**Install:** `uv pip install -e /root/repos/qlib` — builds Cython `_libs` OK (gcc 14 present).

---

## Asset 2: daily_stock_analysis (DSA) — `/root/repos/daily_stock_analysis` (MIT)

**Class 1: Platform Runtime Engine — daily operational intelligence & alerting layer.**

| # | Capability | Module path | Verified | Integration decision |
|---|---|---|---|---|
| 1 | 14-channel notification dispatch: Telegram, Slack, Discord, Email(SMTP), Feishu, WeCom, DingTalk, Pushover, ntfy, Gotify, PushPlus, ServerChan3, AstrBot, Custom webhook | `src/notification_sender/*.py` | ✅ all 14 import in UnlockAid venv | **USE** via adapter; no reimplementation |
| 2 | Unified send contract with per-channel diagnostics, routing (`route_type`), severity, **dedup_key/cooldown** | `src/notification.py::NotificationService.send_with_results` (lines 2453+) | ✅ real HTTP delivery proven to local sink | **USE**; UnlockAid alert-intelligence fills these fields |
| 3 | Config from env (`Config.get_instance()`), channel detection, config validation issues | `src/config.py` | ✅ `CUSTOM_WEBHOOK_URLS` honored | **USE** (adapter sets env before import) |
| 4 | Markdown→image fallback for channels (`markdown_to_image_channels`), report chunking | `src/formatters.py`, `src/md2img.py` | source-inspected | **USE later** (post-MVP, needs wkhtmltopdf) |
| 5 | Daily scheduler + graceful shutdown | `src/scheduler.py` | source-inspected | **REPLACE** with UnlockAid APScheduler (per-portfolio schedules); rationale in DEVIATIONS |
| 6 | Multi-source data fetchers (akshare/tushare/yfinance/baostock/efinance + fallback manager) | `data_provider/` | ✅ importable (`normalize_stock_code`) | **USE later** as Layer A refresh source; MVP uses qlib dump |
| 7 | Watchlist/portfolio services, alerts, backtest engine, market light, decision signals | `src/services/*.py` (`portfolio_alerts`, `alert_indicators`, `market_light_alerts`), `src/core/backtest_engine.py` | source-inspected | **INSPIRE** UnlockAid analysis schema; not imported (Chinese-market A-share pipeline coupling) |
| 8 | LLM analysis pipeline (litellm, prompt packs, strategies YAML) | `src/analyzer.py`, `src/llm/`, `strategies/` | deps installed | **USE later** (Research Explanation agent = litellm; DSA prompt style reference) |

**Import contract:** DSA uses `from src...` absolute imports and top-level package
`src`/`data_provider`. UnlockAid inserts `/root/repos/daily_stock_analysis` at `sys.path[0]`
inside a context manager (isolation; no shadowing leak). Deps installed from
`requirements.txt` minus git+ URLs (alphasift optional).

---

## Asset 3: chenditc/investment_data — `/root/.qlib/qlib_data/cn_data`

**Class 4: Data artifact.** 844 MB qlib binary dump (calendars to 2026-09-04, CSI300
instruments). Downloaded via GitHub latest release. Refresh = re-download (Layer A).
Licensing: derived from public data aggregators; commercial redistribution requires
upstream terms review — flagged in DEVIATIONS §19 (customer must connect own licensed feed
for production tiers; MVP demo-grade).

## Asset 4: DSA strategies (Class 5)
`strategies/*.yaml` — 10+ strategy prompt definitions (bull_trend, bottom_volume,
box_oscillation, chan_theory…). Used as **style references** for the Research Explanation
agent's report templates; no runtime coupling.

## Assets 5+: Playbook & Amendments (Class 5)
`/root/work/ai-company/AGENT_BUILD_PLAYBOOK.md`, `PLAYBOOK_AMENDMENTS_V2.md`,
`POLICY_OBJECTIVE_FIDELITY.md` — govern process/gates; see OBJECTIVE_DECOMPOSITION §2.

---

## Deviations (summary — full text in DEVIATIONS.md)
1. DSA `scheduler.py` replaced by APScheduler — DSA scheduler is single-global-slot
   (`set_daily_task`); UnlockAid needs per-portfolio schedules. DSA send path untouched.
2. qlib online-serving (`PredUpdater`) not used in MVP daily path — requires qlib
   task-server infra; equivalent result via direct `model.predict` on fresh data, same
   qlib code path. Post-MVP switch documented.
3. `alphasift` (git+ dep) skipped — network-optional screening add-on, not required by objective.
4. mlflow file-store opt-in env var — upstream deprecation, not our architecture.

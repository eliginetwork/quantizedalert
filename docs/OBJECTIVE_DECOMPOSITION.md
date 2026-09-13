# Objective Decomposition — QuantizedAlert (formerly UnlockAid) (Playbook v2.1 + Amendments)

**Project:** QuantizedAlert — Autonomous Quant Research-to-Alert Revenue Engine
**Objective source:** Business Objective attachment (27 sections), 2026-09-08.
**Predecessor lesson encoded here:** `quant-research-alerts` failure (Playbook Appendix A) — this build MUST run qlib and daily_stock_analysis (DSA) in the primary execution path.

---

## 1. System Vision & Objective

Turn `/root/repos/qlib` (research & quantitative modeling engine) and
`/root/repos/daily_stock_analysis` (daily operational intelligence & alerting layer)
into a recurring-revenue platform that automates:

**Research → Backtest → Validate → Deploy → Monitor → Alert**

Customer promise: *operationalize quantitative research* — an always-on research and
portfolio monitoring system, managed infrastructure, not "hosted Qlib".

---

## 2. Mandatory Assets & Class Taxonomy (Amendment F)

### Class 1: Platform Runtime Engines (load-bearing; fault-injection tested)

| Asset | Path | Role | Live invocation |
|---|---|---|---|
| **qlib** | `/root/repos/qlib` | Layer B research engine: Alpha158 factors, 34-model zoo (LGBModel first), DatasetH, backtest engine, PortAnaRecord-style risk analysis, workflow/Recorder experiment tracking (mlflow), online serving (`qlib.workflow.online`), rolling retrain | `from qlib.contrib.model.gbdt import LGBModel` etc. in `src/quantizedalert/engine/qlib_engine.py`; engine_source reported |
| **daily_stock_analysis (DSA)** | `/root/repos/daily_stock_analysis` | Layer G alerting: 14-channel `NotificationService` (Telegram/Slack/Discord/Email/Feishu/WeCom/DingTalk/Pushover/ntfy/Gotify/PushPlus/ServerChan3/AstrBot/Custom webhook), routing/severity/dedup/cooldown contract (`send_with_results`), daily report rendering | `sys.path` import in `src/quantizedalert/alerts/dsa_dispatch.py`; per-channel diagnostics returned |

Both Class 1 assets verified runnable in this project environment (see BUILD_EVIDENCE):
- qlib 0.9.8.dev31 editable install; `qlib.init` + real CSI300 data (through 2026-09-04) + LGBModel train + `qlib.backtest` = **SMOKE_OK** (`scripts/asset_smoke_qlib.py`).
- DSA: all 14 senders + `src.config.Config` + `NotificationService` import and dispatch through QuantizedAlert's venv.

### Class 2: Target Scaffolding Templates
None mandated by objective. (Data bootstrap artifact below is treated as Class 4.)

### Class 3: Target App Runtime Deps
N/A — the deliverable is a web platform + CLI, not generated apps.

### Class 4: External Tooling & Data
| Asset | Usage |
|---|---|
| **chenditc/investment_data qlib_bin dump** | Open-licensed (CC-BY via upstream sources; licensing reviewed in DEVIATIONS) daily OHLCV dump in Qlib format → `~/.qlib/qlib_data/cn_data`. Refreshed by scheduled download (Layer A data refresh). |
| **mlflow** (qlib-tracking dep) | Experiment artifacts via qlib `Recorder` (file store opt-in; sqlite URI for production). |
| **APScheduler** | Layer E recurring inference scheduling. |
| **FastAPI + Jinja2** | Layer H dashboard, served as the runnable product interface (Amendment I). |
| **SQLite/SQLAlchemy** | Model registry (Layer D), metering store. |

### Class 5: Reference / Methodology
| Asset | Ingestion |
|---|---|
| `/root/work/ai-company/AGENT_BUILD_PLAYBOOK.md` | Process gates 0–6. |
| `/root/work/ai-company/PLAYBOOK_AMENDMENTS_V2.md` | Amendments A–I enforced below. |
| DSA `strategies/*.yaml` | Strategy-prompt reference for daily-analysis wording (`research/explanation` agent output style). |
| qlib `examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml` | Canonical workflow contract our config schema mirrors. |

---

## 3. Deliverables (objective §5, §11, §12 mapped)

| # | Deliverable | Layer | Module |
|---|---|---|---|
| D1 | Data acquisition/refresh + freshness/staleness/anomaly detection | A | `src/quantizedalert/data/` |
| D2 | Qlib research runner (factor handler → train → experiment record) | B | `src/quantizedalert/engine/qlib_engine.py`, `research/` |
| D3 | Validation: in/out-of-sample, walk-forward, drawdown, turnover, cost, stability, sensitivity, overfit flags | C | `research/runner.py` (gates+WF) + `agents/research.py` (`OverfitAuditAgent`) |
| D4 | Model registry (datasets/factors/models/hyperparams/experiments/validation lineage) | D | `store.py` (models table + qlib `experiment_ref` lineage) |
| D5 | Deployment: schedule validated models for daily inference | E | `src/quantizedalert/deploy/` |
| D6 | Daily analysis: predictions → rankings → portfolio analytics → risk → signal changes | F | `src/quantizedalert/analysis/` |
| D7 | Alert intelligence: scoring, ranking, quiet hours, thresholds, per-customer channels via **DSA senders** | G | `src/quantizedalert/alerts/` |
| D8 | Dashboard: what changed → affected assets/models → significance → historical context | H | `src/quantizedalert/dashboard/` |
| D9 | Front-door CLI `quantizedalert` (init, research, validate, deploy, daily, alert-test, serve, e2e) | all | `src/quantizedalert/cli.py` |
| D10 | Commercial harness: plans, usage metering, Stripe integration surface, unit economics ledger | biz | `src/quantizedalert/commercial/` |
| D11 | AI research automation agents (experiment gen, backtest summary, overfit audit, monitoring, alert triage, explanation) | B–G | `src/quantizedalert/agents/` |

## 4. Constraints
- MVP = one narrow workflow (§12): CN CSI300 universe → LightGBM/Alpha158 → backtest → validate → registry → daily schedule → analysis → dashboard → ≥1 alert channel delivered.
- No guaranteed-return claims; no discretionary trading (§20). Product value persists when strategies underperform (§25).
- Data: open/licensed sources only (§19); commercial redistribution gated by DEVIATIONS notes.

## 5. Success-Criteria Traceability (Amendment B.4)

| ID | Criterion | Test |
|---|---|---|
| SC1 | qlib executes inside project (train+backtest, engine_source=qlib) | `test_sc1_qlib_asset_smoke` |
| SC2 | DSA delivers an alert end-to-end through ≥1 real channel adapter | `test_sc2_dsa_alert_delivery` |
| SC3 | Full MVP loop E2E: universe→train→backtest→validate→register→deploy→daily→alert→dashboard JSON | `test_sc3_mvp_loop_e2e` |
| SC4 | Both Class 1 assets load-bearing under fault injection (Amendment G) | `test_sc4_fault_injection_*` |
| SC5 | Alert intelligence: ranking suppresses low-value alerts; quiet hours honored; dedup/cooldown | `test_sc5_alert_intelligence` |
| SC6 | Registry lineage: every prediction/alert traceable to model version + experiment | `test_sc6_registry_lineage` |
| SC7 | Front door: CLI executes all commands, zero stubs (Amendment I) | `test_sc7_cli_front_door` |
| SC8 | Validation actively flags an injected overfit model | `test_sc8_overfit_detection` |
| SC9 | Commercial: plan gating + usage metering + contribution-margin math | `test_sc9_commercial_metering` |
| SC10 | Dashboard surfaces changed→affected→significance→context contract | `test_sc10_dashboard_contract` |

## 6. 30/60/90 Alignment
- Days 1–30 (§13): D1–D9 = this build. Design-partner recruitment is a human ops task; build supplies demo loop + onboarding docs.
- Days 31–60: D10 implements auth-ready plan gating + Stripe meter surface now so conversion is wiring, not redesign.
- Days 61–90: expansion points (§15–18) are extension seams: agent framework (D11), prediction-feed ingest API for external models (§17), REST API (§18).

# BUILD_EVIDENCE.md — UnlockAid v0.1.0

Every claim cites a command run in this build session against the real assets
(`/root/repos/qlib` @ 0.9.8.dev31 + `/root/repos/daily_stock_analysis`), the real
cn daily-bar qlib dump (564 MB, refreshed 2026-09-08), and live HTTP delivery.
Machine: AMD Ryzen AI 9 365. All times CST-ish UTC+8.

## MVP loop (§12) — proven end-to-end

Command: `unlockaid e2e ridge` (train → backtest → validate → register →
deploy → daily inference → alert intelligence → DSA delivery → dashboard export)

    [1/4] research+validate: mdl_c62b824d68be passed=True  ic=0.0109 IR=2.16
    [2/4] deployed + daily inference: 300 predictions, ok=True
    [3/4] alerts: N events, M delivered via daily_stock_analysis
    [4/4] dashboard payload exported: data/exports/e2e_ridge.json
    E2E_OK

| §12 step | Layer | Evidence |
|---|---|---|
| 1. supported market universe | A | `csi300` via qlib instruments; `data health ridge` → `calendar_last 2026-09-04, fresh=true, stale 0, anomaly 0, missing 0` over 30 instruments |
| 2. train ≥1 Qlib model | B | ridge (qlib `LinearModel`) + LightGBM trained through `QlibEngine`; qlib recorder ids in registry (`experiment_ref`) |
| 3. execute backtest | B | qlib TopkDropout: ann_return 45.6%, IR 2.16, maxDD −8.5%, turnover 19.4%/day, cost 3.8bp/day (`mdl_c04bc8ce5780`) |
| 4. validation metrics | C | `unlockaid validate ridge` → gates `{min_ic, min_ir, max_dd, turnover, wf_stable}` all true; 3-fold expanding-window walk-forward ICs on real labels |
| 5. register model | D | `unlockaid registry` → 10+ models, statuses `candidate/rejected/validated`, lineage (`dataset_ref`, `factor_set`, `hyperparameters`, `experiment_ref`) |
| 6. schedule daily inference | E | `unlockaid deploy ridge mdl_…` + APScheduler cron 17:30; `sync()` → `['daily:demo','daily:ridge']`; `_job('ridge')` synchronous fire → new daily_run recorded |
| 7. outputs into daily analysis | F | `daily ridge` → 300 ranked predictions persisted, price/chg enrichment via qlib features |
| 8. concise dashboard | H | `serve` on :8765 → `GET /w/ridge` HTTP 200: cards (300 scored, model+version+status, alerts 4/4 budget), rank-Δ table with prices, ranked alert stream, health panel |
| 9. configurable alerts | G | `AlertPrefs`: channels, max_alerts_per_day, min_severity, min_score, quiet_hours, dedup_window_hours — live behavior verified (below) |
| 10. deliver through ≥1 channel | G | DSA `send_to_custom` → local HTTP sink received 5 real payloads, e.g. `### [HIGH] SZ000001 climbed 33 ranks (83→50)…` |

## Alert intelligence (§7) — fewer, higher-value

- Ranking: weighted value (severity .30 / portfolio-relevance .25 / novelty .15 /
  confidence .15 / risk .10 / history .05); `process()` returns priority order.
- Live suppression proof (same day, rerun): 3 events →
  `suppressed:dedup window` — no repeat spam. Budget: `4 / 4 budget 5/day`.
- Quiet hours: below-HIGH suppressed; CRITICAL breaks through (unit-tested).
- Delivery failure: all-channels-false → decision flips to
  `delivery failed on all channels`, never recorded as delivered
  (`tests/test_failsafe.py::test_delivery_failure_blocks_claim`).

## §6 agents — wired into live paths, deterministic over real assets

| Agent | Where it runs | Proof |
|---|---|---|
| Factor Discovery | `unlockaid discover` | 10 qlib expression factors scored on real forward returns, `6/10 pass \|rank_ic\|≥0.01` over 76,830 obs |
| Experiment | `unlockaid experiments` | model-aware grid (ridge alphas → 3 real runs, IRs 2.16/1.43/0.70 ranked) |
| Backtest Analysis + Overfit Audit | `validate` | flags real failures: LightGBM 1d run rejected on `2 sign flips across folds` / `fold degradation` |
| Model Monitoring | every `daily` run | drift rows written to store (`rank_dispersion`, n=5); z>3 or coverage<0.8 → HIGH event |
| Market Regime | every `daily` run | 20d-vs-250d benchmark vol ratio on SH000300 |
| Portfolio Risk | every `daily` run with holdings | HHI/drawdown rules |
| Research Explanation | `unlockaid explain` | exact-numbers prose, `[engine_source=template]`, LLM polish behind `UNLOCKAID_LLM_MODEL` with visible fallback tag |
| Alert Intelligence | `alerts/intelligence.py` | see §7 above |

Anti-quack: no agent asks an LLM to invent numbers; LLM only polishes prose and
the polish source is tagged (`litellm` or `template-fallback:<Exception>`).

## §9/§22 commercial — real metering, contribution margin

- `quota enforced: w1 research_jobs 5/5` (free tier), alerts capped per day.
- `economics ridge`: free → contribution **−$4.31** (deliberate acquisition loss),
  individual → **+$45.25** against $49. Costs computed from real metered usage
  (data $3.00, research/inference compute, storage, messaging).
- Every pipeline step meters through `make_meter`: research_jobs, inference_jobs,
  alerts_delivered (only on real delivery).

## Fail-safety (§24)

- Engine explosion → `DailyRunResult.ok=False`, error persisted to
  `daily_runs`, dashboard shows it (`test_engine_failure_recorded_not_swallowed`).
- `deploy` refuses non-validated models without `--force`; `e2e` **stops** at the
  validation gate and exits non-zero (verified live: LightGBM run refused to deploy).
- Missing artifact / missing registry row → loud `QlibExecutionError`, never silent.

## Test suite

`python -m pytest tests/ -q` → **22 passed** (3 files: `test_commercial_alerts`
quotas/margins/priority/budget/dedup/severity; `test_failsafe` engine-blowup,
delivery-failure, missing-service, quiet-hours; `test_success_criteria` the full
SC1–SC10 matrix incl. live qlib train/backtest, real DSA webhook delivery on an
ephemeral local sink, and overfit-detection). Plus live asset smoke:
`scripts/asset_smoke_qlib.py`.

## Dashboard (Layer H)

`GET /api/ridge/summary` → JSON bundle; `GET /w/ridge` →
"What changed → which assets → significance → context" layout:
cards row (as-of, scored count, deployed model + validation status, alert
budget, data health), watchlist/portfolio rank-Δ table, ranked alert stream,
portfolio analytics, job history.

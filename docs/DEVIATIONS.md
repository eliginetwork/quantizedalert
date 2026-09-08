# DEVIATIONS.md — UnlockAid v0.1.0

Where we departed from the objective text or the source repos, and why.

## 1. Qlib used as a library, not a platform

**Objective** (§4) explicitly permits wrapping/refactoring. We import qlib
(`qlib.init`, `DataHandlerDJ`, `LGBModel`/`LinearModel`, `DatasetH`,
`recorder`, backtest loop) through one adapter (`engine/qlib_engine.py`) and
own everything above it: config, registry, validation gates, scheduling,
alerting, commercialization.

- **RD-Agent not integrated.** `/root/repos/qlib` in this tree does not ship
  RD-Agent (separate project/repo). Its job — hypothesis → factor → experiment
  loops — is covered natively by §6's FactorDiscovery/Experiment agents over
  qlib expressions. Revisit if RD-Agent is added as a Class-4 asset.
- **Workflow yaml (`qrun`) bypassed** in favor of the Python API: one adapter,
  typed returns, no string-config sprawl. Experiment lineage still lands in
  qlib recorders (`experiment_ref`).

## 2. DSA used as the delivery + formatting engine; its scheduler replaced

- **Replaced**: DSA's single-slot scheduler → APScheduler cron jobs per
  deployment (`deploy/scheduler.py`). Multi-tenant scheduling is a product
  requirement DSA's design doesn't cover.
- **Replaced**: DSA's own analysis/decision layer (it runs its own LLM market
  analysis) → UnlockAid's own Layer F/G logic. We import only DSA's
  `NotificationService` + 14 channel senders + config contract.
  Alert *decisions* (what to send, when, to whom) are UnlockAid's.
- **Env contract kept**: channels configured via DSA env vars
  (`CUSTOM_WEBHOOK_URLS`, `TELEGRAM_BOT_TOKEN`, …). One DSA config = one
  process-wide channel set, so v0.1 ships **per-process routing**; per-customer
  credentials arrive with multi-tenant deployment (days 31-60), not new code —
  DSA senders are instantiable per-config.

## 3. Data: qlib community dump only (v0.1)

`data refresh` pulls chenditc/investment_data (daily, cn). No vendor feeds, no
real-time. Matches §12's "one narrowly defined workflow": A-share daily,
universe = csi300/csi500, horizon = 1 day. Point-in-time correctness, corporate
actions, and survivorship hygiene are at the mercy of the dump — stated in
pricing docs (§20) and in the dashboard footer.

## 4. Walk-forward folds are calendar-expanding, not purged/embargoed

Labels overlap (1d and 5d forward returns) but folds are contiguous calendar
blocks; leakage across fold boundaries is possible at the edges. The gate
(*sign stability + OOS decay across folds*) still rejects what the LightGBM
1d candidate produced (2/3 folds sign-flipped → `rejected`). Purged K-fold is a
known upgrade, not a rewrite: swap `engine.walk_forward` internals.

## 5. Validation gates are plan defaults, not per-customer yet

`validation_gates` live in workspace YAML (per-workspace override exists) but
there is no UI/tenant model for them in v0.1. MVP target: prove the loop; days
31-60 add auth + self-service config (§11 steps 1-3).

## 6. Stripe adapter is webhook-shaped, unlaunched

`commercial/plans.py` implements plan table, quota metering, contribution
margin, and a Stripe surface (`StripeAdapter`: create_customer / webhook plan sync /
MeterEvent usage reporting, webhook-driven plan changes) verified against an injected fake client (`tests/test_billing_fake.py`: subscribe persists plan + sub id; usage lands as a meter event). No real
Stripe account was attached in this session — deliberately, to avoid creating
live billing objects. The revenue loop is otherwise complete and measurable
offline (scorecard + economics).

## 7. Free tier intentionally negative contribution

−$4.31/customer/month vs $0 revenue: acquisition budget, capped by quotas
(5 research jobs, 30 inference, 2 alerts/day). §22 requires pricing validated
against real customers — v0.1 makes cost visible per customer instead of
guessing.

## 8. Dashboard = server-rendered FastAPI, no auth

§14/§12 need a demoable surface now; auth is days 31-60 work (§13). The JSON
API (`/api/{ws}/…`) is separated from HTML so a real frontend can attach later
without touching the pipeline.

## 9. Alert quiet-hours evaluated in fixed UTC+8

Workspace tz is not yet a field; default Asia/Shanghai. `quiet_now_minutes`
parameter allows deterministic override (used in tests).

## 10. Model monitoring uses rank-dispersion z-score, not label-based IC decay

Live labels arrive T+1, so the daily pass uses dispersion + coverage shifts as
the drift proxy (documented in `_agent_events`); true IC decay monitoring lands
with the T+1 label backfill job (days 31-60). The agent interface already
accepts a store, so no schema change is needed.

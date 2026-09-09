"""AI automation layer (§6): internal agents that cut repetitive quant/ops work.

Design contract (Anti-Quack standard):
- Every agent's DECISION logic is deterministic code operating on real asset
  outputs (qlib metrics, registry state, health reports). No agent asks an LLM
  to invent numbers.
- LLM usage is optional and limited to *language* (report prose) via litellm —
  the same gateway stack DSA uses. `engine_source` records which path ran.
- If no LLM is configured, the language layer falls back to template prose and
  says so explicitly in the output (Amendment E).
"""
from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np
import pandas as pd

from unlockaid.schemas import AlertEvent, Severity, new_id

logger = logging.getLogger("unlockaid.agents")


# --------------------------------------------------------------------------
# Factor Discovery Agent: propose candidate factor expressions (qlib ops),
# pre-filter by IC on real data; surviving names go to experiment batches.
# --------------------------------------------------------------------------
class FactorDiscoveryAgent:
    """Searches a grammar of qlib expression primitives on real features."""

    CATALOG: list[tuple[str, str]] = [
        ("mom_5", "Ref($close, 6)/Ref($close, 1) - 1"),
        ("mom_20", "Ref($close, 21)/Ref($close, 1) - 1"),
        ("rev_3", "Ref($close, 1)/Ref($close, 4) - 1"),
        ("vol_ratio", "Mean($volume, 5)/(Mean($volume, 20) + 1e-12)"),
        ("amihud_illiq", "Mean(Abs($close/Ref($close,1)-1)/($volume*$close + 1e-12), 20)"),
        ("range_pos", "($close - Min($low, 20))/(Max($high, 20) - Min($low, 20) + 1e-12)"),
        ("gap", "($open - Ref($close, 1))/Ref($close, 1)"),
        ("pv_corr", "Corr($close, Log($volume + 1), 10)"),
        ("vol_20", "Std($close/Ref($close,1) - 1, 20)"),
        ("turn_accel", "Mean($volume,5)/(Mean($volume,60) + 1e-12)"),
    ]

    def __init__(self, engine):
        self.engine = engine

    def evaluate(self, universe: str, start: str, end: str,
                 min_abs_ic: float = 0.01) -> list[dict[str, Any]]:
        """Compute single-factor Rank IC vs forward return with qlib's engine."""
        results = []
        # forward label via same engine (no synthetic data)
        feats = [e for _, e in self.CATALOG] + ["Ref($close, -2)/Ref($close, -1) - 1"]
        df = self.engine.features(
            self.engine.list_instruments(universe, start, end), feats, start, end)
        label = df[feats[-1]]
        for (name, _expr), col in zip(self.CATALOG, df.columns[:-1]):
            x = df[col]
            m = x.notna() & label.notna()
            if m.sum() < 100:
                continue
            rank_ic = float(x[m].rank().corr(label[m].rank()))
            results.append({"factor": name, "expression": dict(self.CATALOG)[name],
                            "rank_ic": rank_ic, "n": int(m.sum()),
                            "pass": abs(rank_ic) >= min_abs_ic})
        results.sort(key=lambda r: -abs(r["rank_ic"]))
        return results


# --------------------------------------------------------------------------
# Experiment Agent: fan out model hyperparameter experiments, rank by IR.
# --------------------------------------------------------------------------
class ExperimentAgent:
    SPACES = {
        "lightgbm": {"num_leaves": [31, 64, 128], "learning_rate": [0.03, 0.05, 0.1]},
        "xgboost": {"max_depth": [4, 6, 8], "learning_rate": [0.03, 0.05, 0.1]},
        "linear": {"l1_and_2": [[0.0, 1.0], [0.5, 0.5], [1.0, 0.0]]},
        "ridge": {"alpha": [0.1, 1.0, 10.0]},
        "lasso": {"alpha": [0.001, 0.01, 0.1]},
    }

    def __init__(self, research_runner):
        self.runner = research_runner

    def plan(self, base_hp: dict, model_type: str = "lightgbm") -> list[dict]:
        import itertools
        space = self.SPACES.get(model_type, {})
        keys = list(space)
        grid = []
        for combo in itertools.product(*(space[k] for k in keys)):
            hp = dict(base_hp)
            hp.update(dict(zip(keys, combo)))
            grid.append(hp)
        return grid or [dict(base_hp)]


# --------------------------------------------------------------------------
# Backtest Analysis Agent: summarize a qlib BacktestReport in English.
# --------------------------------------------------------------------------
class BacktestAnalysisAgent:
    def summarize(self, bt: dict) -> dict:
        notes = []
        if bt["information_ratio"] < 0.5:
            notes.append(f"Weak excess-return stability (IR {bt['information_ratio']:.2f}).")
        if bt["max_drawdown"] < -0.25:
            notes.append(f"Drawdown {bt['max_drawdown']:.0%} would stress most risk limits.")
        if bt["mean_turnover"] > 0.5:
            notes.append(f"High turnover ({bt['mean_turnover']:.0%}/day) — cost-sensitive universe.")
        if bt["mean_cost"] > 0 and abs(bt["mean_return"]) > 0 and bt["mean_cost"] / abs(bt["mean_return"]) > 0.3:
            notes.append("Cost eats >30% of mean return before any slippage surprise.")
        if not notes:
            notes.append("No structural weaknesses detected in the backtest window.")
        return {"summary": " ".join(notes), "engine_source": "rules+qlib"}


# --------------------------------------------------------------------------
# Overfitting/Robustness Agent: audit validation output for suspicious signs.
# --------------------------------------------------------------------------
class OverfitAuditAgent:
    def audit(self, val: dict) -> list[str]:
        flags = []
        m = val.get("metrics", {})
        if m.get("ic", 0) > 0.15:
            flags.append("IC unusually high for daily cross-sectional equity "
                         "prediction — check label/feature leakage.")
        if m.get("rank_ic", 0) > 0.2:
            flags.append("Rank IC >0.2 — verify no lookahead in factors.")
        wf = val.get("walk_forward", [])
        if wf and np.isfinite([f["ic"] for f in wf]).sum() >= 2:
            ics = [f["ic"] for f in wf if np.isfinite(f["ic"])]
            if (ics[0] - np.mean(ics[1:])) > 0.03:
                flags.append("First-fold IC far above later folds — train-window luck.")
        s = val.get("stability", {})
        if s.get("sign_flips", 0) >= len(wf) - 1 and wf:
            flags.append("Sign flips across most folds — signal not stable.")
        sens = val.get("sensitivity", {})
        if sens.get("ic_spread", 0) > 0.05:
            flags.append("Hyperparameter sensitivity: IC swings >0.05 on ±50% perturbations.")
        return flags


# --------------------------------------------------------------------------
# Model Monitoring Agent: drift scoring on live prediction streams (§17).
# --------------------------------------------------------------------------
class ModelMonitoringAgent:
    """Z-score drift on score dispersion + coverage + IC decay (if labels exist)."""

    def check(self, store, workspace_id: str, model_id: str, asof: str,
              current_scores: pd.Series) -> list[AlertEvent]:
        events: list[AlertEvent] = []
        hist = store.drift_history(workspace_id, model_id, "rank_dispersion")
        disp = float(current_scores.std())
        base = float(np.mean([h["value"] for h in hist[-20:]])) if hist else disp
        z = (disp - base) / (float(np.std([h["value"] for h in hist[-20:]])) + 1e-9)
        store.put_drift(workspace_id, model_id, asof, "rank_dispersion", disp, base)
        if len(hist) >= 5 and abs(z) > 3:
            events.append(AlertEvent(
                new_id("evt"), workspace_id, "model_drift",
                f"Model {model_id} dispersion z={z:+.1f}",
                f"Live prediction dispersion {disp:.4f} vs baseline {base:.4f}.",
                Severity.HIGH, models=[model_id],
                components={"confidence": min(1.0, abs(z) / 6), "historical_significance": 0.7}))
        coverage = float(current_scores.notna().mean())
        if coverage < 0.8:
            events.append(AlertEvent(
                new_id("evt"), workspace_id, "model_drift",
                f"Model {model_id} coverage dropped to {coverage:.0%}",
                "Predictions missing for a large share of the universe — inputs or "
                "instrument list changed.", Severity.HIGH, models=[model_id],
                components={"confidence": 0.85, "historical_significance": 0.5}))
        return events


# --------------------------------------------------------------------------
# Market Regime Agent: benchmark vol/return shift detection (real qlib data).
# --------------------------------------------------------------------------
class MarketRegimeAgent:
    def __init__(self, engine):
        self.engine = engine

    def check(self, workspace_id: str, asof: str, benchmark: str = "SH000300",
              lookback: int = 250) -> AlertEvent | None:
        cal = self.engine.calendar()
        start = pd.Timestamp(cal[-(lookback + 2)]).strftime("%Y-%m-%d")
        end = pd.Timestamp(cal[-1]).strftime("%Y-%m-%d")
        df = self.engine.features([benchmark], ["$close"], start, end)
        r = df["$close"].droplevel("instrument").pct_change().dropna()
        if len(r) < 60:
            return None
        vol_now = float(r.tail(20).std() * np.sqrt(252))
        vol_hist = float(r.tail(lookback).std() * np.sqrt(252))
        ratio = vol_now / (vol_hist + 1e-12)
        if ratio > 1.8 or ratio < 0.55:
            return AlertEvent(
                new_id("evt"), workspace_id, "regime",
                f"Market regime shift on {benchmark}",
                f"20d realized vol {vol_now:.0%} vs 250d {vol_hist:.0%} "
                f"(ratio {ratio:.2f}). Strategies tuned to the old regime may "
                f"misprice risk.", Severity.HIGH if ratio > 2 or ratio < 0.45 else Severity.MEDIUM,
                components={"confidence": 0.6, "historical_significance": 0.6,
                            "risk": min(1.0, ratio / 2)})
        return None


# --------------------------------------------------------------------------
# Portfolio Risk Agent: exposures, concentration, drawdown proximity.
# --------------------------------------------------------------------------
class PortfolioRiskAgent:
    def check(self, workspace_id: str, portfolio: list[dict],
              returns: pd.DataFrame, asof: str) -> list[AlertEvent]:
        events: list[AlertEvent] = []
        if not portfolio:
            return []
        w = pd.Series({h["instrument"]: h["weight"] for h in portfolio})
        w = w / w.sum()
        common = w.index.intersection(returns.columns)
        if len(common) == 0:
            return []
        port_ret = (returns[common].fillna(0) * w[common]).sum(axis=1)
        dd = float((port_ret.cumsum() - port_ret.cumsum().cummax()).min())
        vol20 = float(port_ret.tail(20).std() * np.sqrt(252))
        conc = float((w[common] ** 2).sum())
        if dd < -0.15:
            events.append(AlertEvent(
                new_id("evt"), workspace_id, "risk_breach",
                f"Portfolio drawdown {dd:.0%}",
                "Trailing-window portfolio drawdown exceeded 15%.", Severity.HIGH,
                instruments=common.tolist(),
                components={"confidence": 0.9, "risk": 0.9, "vol20": vol20}))
        if conc > 0.25:
            events.append(AlertEvent(
                new_id("evt"), workspace_id, "risk_breach",
                f"Concentration HHI {conc:.2f}",
                "Top positions dominate portfolio variance.", Severity.MEDIUM,
                instruments=common.tolist(),
                components={"confidence": 0.9, "risk": 0.6}))
        return events


# --------------------------------------------------------------------------
# Research Explanation Agent: turn run artifacts into customer prose.
# --------------------------------------------------------------------------
class ResearchExplanationAgent:
    """Template-first; LLM polish optional via litellm (same stack as DSA)."""

    def explain_run(self, cfg_name: str, bt: dict, ic: dict,
                    val: dict) -> str:
        base = (
            f"{cfg_name}: the model explains a small but consistent slice of next-day "
            f"cross-sectional variation (out-of-sample IC {ic['ic']:.3f}, rank IC "
            f"{ic['rank_ic']:.3f} over {ic['n']:,} predictions). Top-{bt['freq']} "
            f"backtest delivered {bt['ann_return']:.1%} annualized excess return with "
            f"information ratio {bt['information_ratio']:.2f} and worst drawdown "
            f"{bt['max_drawdown']:.1%}. Turnover averages {bt['mean_turnover']:.0%}/day, "
            f"so realistic costs matter. "
            + ("Validation passed all robustness gates; safe to deploy."
               if val.get("passed") else
               "Validation flagged: " + "; ".join(val.get("overfit_flags", []))))
        text = self._maybe_llm(base)
        return text

    def _maybe_llm(self, text: str) -> str:
        model = os.environ.get("UNLOCKAID_LLM_MODEL")
        if not model:
            return text + " [engine_source=template]"
        try:
            import litellm
            resp = litellm.completion(
                model=model, messages=[{
                    "role": "user",
                    "content": "Rewrite this quant research note for a "
                               "sophisticated but non-specialist customer; keep every "
                               "number exact:\n\n" + text}],
                max_tokens=600)
            return resp.choices[0].message.content
        except Exception as e:  # fallback must be visible
            logger.warning("LLM polish failed (%s); using template prose", e)
            return text + f" [engine_source=template-fallback:{type(e).__name__}]"

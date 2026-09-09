"""Layers D+E+F+G orchestration: the daily production run.

1. Load the deployed model (registry, Layer D).
2. Refresh features through qlib on the latest calendar day (Layer E inference).
3. Score → rank watchlist/universe (Layer F).
4. Compute portfolio analytics + signal changes.
5. Emit candidate events → Alert Intelligence scores → DSA delivery (Layer G).
6. Persist run + predictions + alert log.

Fail-safety (§24): any qlib failure aborts with an error event, never silent
zero-output; the dashboard then shows the failed run with a CRITICAL alert
through the normal pipeline.
"""
from __future__ import annotations

import logging
import os

import numpy as np
import pandas as pd

from unlockaid.alerts.intelligence import AlertIntelligence
from unlockaid.config import WorkspaceConfig
from unlockaid.data.health import check_health
from unlockaid.engine.qlib_engine import QlibEngine, QlibExecutionError
from unlockaid.schemas import (
    AlertEvent,
    DailyRunResult,
    DataHealthStatus,
    Prediction,
    Severity,
    SignalChange,
    new_id,
)
from unlockaid.store import Store

logger = logging.getLogger("unlockaid.daily")


class DailyPipeline:
    def __init__(self, engine: QlibEngine, store: Store, intelligence: AlertIntelligence):
        self.engine = engine
        self.store = store
        self.intelligence = intelligence

    # ---------- inference ----------
    def inference(self, cfg: WorkspaceConfig, model_id: str, meter=None,
                  asof: str | None = None) -> pd.Series:
        rec = self.store.get_model(model_id)
        if rec is None:
            raise QlibExecutionError(f"model {model_id} not in registry")
        art = rec["artifact_path"]
        if not art:
            raise QlibExecutionError(
                f"model {model_id} has no artifact_path (never trained here?)")
        model = self.engine.load_model(os.path.join(art, "model.dill"),
                                       rec["hyperparameters"].get("type", cfg.model_type))
        # latest-day feature window: handler end = calendar last, start = lookback
        cal = self.engine.calendar()
        if asof:
            cal = [d for d in cal if str(d)[:10] <= asof]
            if not cal:
                raise QlibExecutionError(f"calendar has no bars up to {asof}")
        if len(cal) < 20:
            raise QlibExecutionError(
                f"calendar has only {len(cal)} bars (<20) — insufficient history "
                "for daily inference features")
        last = pd.Timestamp(cal[-1]).strftime("%Y-%m-%d")
        start = pd.Timestamp(cal[-80]).strftime("%Y-%m-%d")
        ds = self.engine.build_dataset(
            rec["factor_set"], cfg.universe or cfg.instruments,
            [start, last], cfg.fit_range, {"latest": [start, last]})
        pred = self.engine.predict_latest(model, ds, segment="latest").dropna()
        if meter:
            meter(cfg.workspace_id, "inference_jobs", 1, ref=model_id)
        return pred

    # ---------- analytics ----------
    def portfolio_analytics(self, cfg: WorkspaceConfig,
                            scores: pd.Series) -> dict:
        """Concentration, volatility, rank-weighted exposure, drift proxy (§16)."""
        held = {h["instrument"]: h["weight"] for h in cfg.portfolio}
        if cfg.portfolio:
            w = np.array(list(held.values()))
            w = w / w.sum()
            conc = float(np.sum(w ** 2))
            # weighted mean score: portfolio alignment with the model
            ws = []
            for inst in held:
                try:
                    ws.append(float(scores.xs(inst, level="instrument").iloc[-1]))
                except KeyError:
                    ws.append(np.nan)
            ws_arr = np.array(ws, dtype=float)
            aligned = np.isfinite(ws_arr)
            weighted_score = float(np.average(ws_arr[aligned], weights=w[aligned])) \
                if aligned.any() else None
        else:
            conc, weighted_score = None, None
        top = scores.sort_values(ascending=False).head(10)
        return {"n_scored": int(scores.shape[0]), "concentration": conc,
                "weighted_model_score": weighted_score,
                "top10": [{"instrument": i, "score": round(float(s), 5)}
                          for i, s in top.items()]}

    def changes(self, cfg: WorkspaceConfig, asof: str, model_id: str,
                ranked: pd.DataFrame) -> list[SignalChange]:
        prev = {p["instrument"]: p for p in
                self.store.get_previous_predictions(cfg.workspace_id, model_id, asof)}
        out: list[SignalChange] = []
        for r in ranked.itertuples():
            p = prev.get(r.instrument)
            rank_delta = (p["rank"] - r.rk) if p else None
            out.append(SignalChange(
                instrument=r.instrument, asof=asof,
                previous_rank=p["rank"] if p else None, rank=int(r.rk),
                previous_score=p["score"] if p else None,
                score=float(r.score), rank_delta=rank_delta,
                price=getattr(r, "price", None),
                price_change_pct=getattr(r, "chg", None)))
        return out

    # ---------- event generation ----------
    def candidate_events(self, cfg: WorkspaceConfig, asof: str,
                         health, ranked: pd.DataFrame,
                         changes: list[SignalChange],
                         model_id: str) -> list[AlertEvent]:
        ws = cfg.workspace_id
        events: list[AlertEvent] = []
        # 1) data health
        if health is not None and not health.fresh:
            events.append(AlertEvent(
                new_id("evt"), ws, "data_stale",
                f"Market data stale (last bar {health.calendar_last})",
                f"Calendar last bar is **{health.calendar_last}** — daily analysis may "
                f"use outdated inputs. Refresh with `unlockaid data refresh`.",
                Severity.CRITICAL, models=[model_id],
                components={"confidence": 0.95, "historical_significance": 0.6}))
        stale_assets = [a for a in health.assets
                        if a.status in (DataHealthStatus.STALE, DataHealthStatus.MISSING)] \
            if health else []
        if stale_assets:
            names = ", ".join(a.instrument for a in stale_assets[:5])
            events.append(AlertEvent(
                new_id("evt"), ws, "data_stale",
                f"{len(stale_assets)} instrument(s) missing/stale bars",
                f"Affected: {names}. Model predictions for these names are suppressed.",
                Severity.HIGH, instruments=[a.instrument for a in stale_assets]))
        anomalies = [a for a in (health.assets if health else [])
                     if a.status is DataHealthStatus.ANOMALY]
        for a in anomalies:
            events.append(AlertEvent(
                new_id("evt"), ws, "anomaly",
                f"Data anomaly on {a.instrument}",
                f"Detected: {', '.join(a.anomalies)} at last bar {a.last_bar}.",
                Severity.MEDIUM, instruments=[a.instrument],
                components={"confidence": 0.8}))
        # 2) signal changes for watchlist / held names
        held = set(cfg.watchlist) | {h["instrument"] for h in cfg.portfolio}
        big = [c for c in changes if c.rank_delta is not None
               and abs(c.rank_delta) >= 10 and (not held or c.instrument in held)]
        for c in sorted(big, key=lambda x: -abs(x.rank_delta))[:3]:
            direction = "climbed" if c.rank_delta > 0 else "fell"
            sev = Severity.HIGH if abs(c.rank_delta) >= 25 else Severity.MEDIUM
            events.append(AlertEvent(
                new_id("evt"), ws, "signal_change",
                f"{c.instrument} {direction} {abs(c.rank_delta)} ranks ({c.previous_rank}→{c.rank})",
                f"Model score {c.previous_score:.4f} → {c.score:.4f}. "
                f"Price {c.price:.2f} ({c.price_change_pct:+.2%})" if c.price else
                f"Model score {c.previous_score:.4f} → {c.score:.4f}.",
                sev, instruments=[c.instrument], models=[model_id],
                components={"confidence": 0.6,
                            "historical_significance": min(1.0, abs(c.rank_delta) / 50)}))
        # 3) §6 agent swarm on live state (deterministic rules over real assets)
        events += self._agent_events(cfg, asof, model_id, ranked)
        # dedup keys: one per kind per day
        for e in events:
            e.dedup_key = f"{ws}:{e.kind}:{':'.join(sorted(e.instruments)[:3])}"
        return events

    def _agent_events(self, cfg: WorkspaceConfig, asof: str, model_id: str,
                      ranked: pd.DataFrame) -> list[AlertEvent]:
        """§6: Model Monitoring + Market Regime + Portfolio Risk agents run on
        every daily pass. Decision logic is deterministic code over real qlib
        outputs (Anti-Quack standard); an agent failure is logged and does NOT
        abort the run — predictions are already computed."""
        from unlockaid.agents.research import (
            MarketRegimeAgent,
            ModelMonitoringAgent,
            PortfolioRiskAgent,
        )
        events: list[AlertEvent] = []
        try:
            events += ModelMonitoringAgent().check(
                self.store, cfg.workspace_id, model_id, asof,
                ranked["score"].reset_index(drop=True))
        except Exception as e:
            logger.error("ModelMonitoringAgent failed: %s", e)
        try:
            ev = MarketRegimeAgent(self.engine).check(
                cfg.workspace_id, asof,
                benchmark=cfg.backtest.get("benchmark", "SH000300"))
            if ev:
                events.append(ev)
        except Exception as e:
            logger.error("MarketRegimeAgent failed: %s", e)
        try:
            if cfg.portfolio:
                insts = [h["instrument"] for h in cfg.portfolio]
                cal = self.engine.calendar()
                start = pd.Timestamp(cal[-31]).strftime("%Y-%m-%d")
                end = pd.Timestamp(cal[-1]).strftime("%Y-%m-%d")
                fx = self.engine.features(insts, ["$close"], start, end)
                rets = (fx["$close"].unstack("instrument")
                        .pct_change().dropna(how="all"))
                events += PortfolioRiskAgent().check(
                    cfg.workspace_id, cfg.portfolio, rets, asof)
        except Exception as e:
            logger.error("PortfolioRiskAgent failed: %s", e)
        return events

    def run(self, cfg: WorkspaceConfig, asof: str | None = None,
            meter=None) -> DailyRunResult:
        ws = cfg.workspace_id
        dep = self.store.get_deployment(ws)
        if not dep or not dep["enabled"]:
            raise RuntimeError(f"no enabled deployment for {ws}; `unlockaid deploy` first")
        model_id = dep["model_id"]
        engine_sources = {"research_engine": "qlib",
                          "data_refresh": "qlib",
                          "delivery": "daily_stock_analysis"}
        try:
            # health instruments: explicit list, else resolved from the universe
            # (an empty list would make the check vacuous — no asset can ever
            # be flagged STALE/MISSING). Any engine failure here degrades to a
            # recorded health error — health must never crash the run unrecorded.
            health_insts = cfg.instruments or self.engine.list_instruments(
                cfg.universe, cfg.handler_range[0], cfg.handler_range[1])
            health = check_health(self.engine, cfg.universe, health_insts)
        except Exception as e:  # noqa: BLE001 — fail-safe, recorded, not silent
            health = None
            self.store.put_data_health(ws, str(asof or "n/a"), "error", {"error": str(e)})
        try:
            pred = self.inference(cfg, model_id, meter=meter, asof=asof)
            if health is not None:
                bad = {a.instrument for a in health.assets
                       if a.status is DataHealthStatus.MISSING}
                if bad:
                    pred = pred[~pred.index.get_level_values("instrument").isin(bad)]
            last_day = pred.index.get_level_values("datetime").max()
            scores = pred[pred.index.get_level_values("datetime") == last_day]
            scores = scores.droplevel("datetime").sort_values(ascending=False)
            asof = asof or last_day.strftime("%Y-%m-%d")
            ranked = pd.DataFrame({"instrument": scores.index,
                                   "score": scores.to_numpy()})
            # NB: no column literally named "rank" — itertuples would rename it
            ranked["rk"] = np.arange(1, len(ranked) + 1)
            # enrich with latest price/change via qlib
            insts = ranked["instrument"].tolist()
            # price/change window: only the last few calendar days are needed
            price_cal = [str(d)[:10] for d in self.engine.calendar()]
            if asof:
                price_cal = [d for d in price_cal if d <= str(asof)[:10]]
            price_start = pd.Timestamp(price_cal[-6]).strftime("%Y-%m-%d")
            fx = self.engine.features(insts, ["$close", "Ref($close,1)"],
                                      price_start, asof)
            chg = {}
            for inst, g in fx.groupby(level="instrument"):
                g = g.droplevel("instrument").sort_index().tail(2)
                if len(g) == 2:
                    chg[inst] = (float(g["$close"].iloc[-1]),
                                 float(g["$close"].iloc[-1] / g["Ref($close,1)"].iloc[-1] - 1))
            ranked["price"] = [chg.get(i, (np.nan, np.nan))[0] for i in ranked.instrument]
            ranked["chg"] = [chg.get(i, (np.nan, np.nan))[1] for i in ranked.instrument]

            self.store.put_predictions([{
                "workspace_id": ws, "model_id": model_id, "instrument": r.instrument,
                "asof": asof, "score": float(r.score), "rank": int(r.rk)}
                for r in ranked.itertuples()])

            portfolio = self.portfolio_analytics(cfg, scores)
            changes = self.changes(cfg, asof, model_id, ranked)
            events = self.candidate_events(cfg, asof, health, ranked, changes, model_id)
            decisions = self.intelligence.process(
                events, ws, asof,
                held_instruments=set(cfg.watchlist) | {h["instrument"] for h in cfg.portfolio})
            result = DailyRunResult(
                workspace_id=ws, asof=asof, ok=True, data_health=health,
                predictions=[Prediction(i, asof, model_id, float(s), int(k), ws)
                             for k, (i, s) in enumerate(
                                 zip(ranked.instrument, ranked.score), start=1)],
                changes=changes, portfolio=portfolio, alerts=decisions,
                model_id=model_id, engine_sources=engine_sources)
            self.store.put_daily_run(ws, asof, True, model_id, None, result.to_dict())
            self.store.put_job(new_id("job"), ws, "daily_run", "done",
                               result={"asof": asof, "model_id": model_id,
                                       "n_predictions": len(result.predictions),
                                       "n_alerts_delivered": sum(
                                           1 for d in decisions if d.deliver)})
            if meter:
                meter(ws, "alerts_generated", len(events))
                meter(ws, "alerts_delivered", sum(1 for d in decisions if d.deliver))
            return result
        except QlibExecutionError as e:
            logger.error("daily run failed for %s: %s", ws, e)
            crit = AlertEvent(new_id("evt"), ws, "job_failure",
                              f"Daily inference failed: {ws}",
                              f"qlib error: {e}. No predictions were produced "
                              "(failing safely, not silently).",
                              Severity.CRITICAL, models=[model_id],
                              components={"confidence": 0.95, "historical_significance": 0.5})
            decisions = self.intelligence.process([crit], ws, str(asof), set())
            result = DailyRunResult(workspace_id=ws, asof=str(asof or ""), ok=False,
                                    data_health=health, predictions=[], changes=[],
                                    portfolio={}, alerts=decisions, model_id=model_id,
                                    error=str(e), engine_sources=engine_sources)
            self.store.put_daily_run(ws, str(asof or ""), False, model_id, str(e),
                                     result.to_dict())
            self.store.put_job(new_id("job"), ws, "daily_run", "error",
                               error=str(e))
            return result

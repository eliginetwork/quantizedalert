"""Layers B+C — research runner: config → qlib train → backtest → validate.

Thin glue over `engine.qlib_engine` (the qlib asset). Nothing here reimplements
factor generation, training, backtesting, or risk analysis.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Optional

import numpy as np
import pandas as pd

from unlockaid.config import WorkspaceConfig
from unlockaid.engine.qlib_engine import QlibEngine
from unlockaid.schemas import (BacktestReport, ModelRecord, ModelStatus,
                               ValidationResult, new_id)
from unlockaid.store import Store, utcnow

logger = logging.getLogger("unlockaid.research")

DEFAULT_GATES = {
    "min_ic": 0.005,          # tiny but real signal; §25: no single-Sharpe kill rule
    "min_ir": 0.2,
    "min_maxdd": -0.35,
    "max_turnover": 0.9,
    "max_ic_std": 0.10,
    "max_degradation": 1.5,
    "wf_splits": 3,
    "param_sensitivity": False,
}


class ResearchRunner:
    def __init__(self, engine: QlibEngine, store: Store, artifact_root: str):
        self.engine = engine
        self.store = store
        self.artifact_root = artifact_root
        self._runs: dict[str, dict] = {}

    # ---------- training ----------
    def train(self, cfg: WorkspaceConfig, meter=None) -> ModelRecord:
        """Full research run on a workspace config using real qlib.

        Returns a CANDIDATE ModelRecord (promotion happens in validate()).
        """
        self.engine.init()
        model_id = new_id("mdl")
        instruments = cfg.universe or cfg.instruments
        ds = self.engine.build_dataset(
            cfg.factor_set, instruments, cfg.handler_range, cfg.fit_range,
            cfg.train_segments)
        model = self.engine.build_model(cfg.model_type, cfg.hyperparameters)
        mlruns_dir = os.path.join(self.artifact_root, "mlruns", cfg.workspace_id)
        test_pred, meta = self.engine.train(
            model, ds, experiment_name=f"{cfg.workspace_id}:{model_id}",
            recorder_dir=mlruns_dir)
        test_pred = test_pred.dropna()

        ic = self.engine.ic(ds, test_pred, "test")
        bt = self.engine.backtest(
            test_pred, cfg.train_segments["test"][0], cfg.train_segments["test"][1],
            topk=cfg.backtest["topk"], n_drop=cfg.backtest["n_drop"],
            account=cfg.backtest["account"], benchmark=cfg.backtest["benchmark"])

        art_dir = os.path.join(self.artifact_root, "models", cfg.workspace_id, model_id)
        os.makedirs(art_dir, exist_ok=True)
        self.engine.save_model(model, os.path.join(art_dir, "model.dill"))
        with open(os.path.join(art_dir, "backtest.json"), "w") as f:
            json.dump(BacktestReport(**bt).to_dict(), f)
        test_pred.rename("score").to_frame().to_csv(
            os.path.join(art_dir, "test_predictions.csv"))

        rec = ModelRecord(
            model_id=model_id, name=f"{cfg.model_type}-{cfg.factor_set}",
            version=uuid.uuid4().hex[:6], status=ModelStatus.CANDIDATE,
            dataset_ref=f"{cfg.factor_set}/{cfg.universe}/{cfg.handler_range[0]}..{cfg.handler_range[1]}",
            factor_set=cfg.factor_set,
            hyperparameters=dict(cfg.hyperparameters),
            experiment_ref=meta["recorder_id"],
            artifact_path=art_dir,
            validation=None,
            created_at=utcnow(), created_by=f"workspace:{cfg.workspace_id}",
            engine_source="qlib")
        payload = rec.to_dict()
        payload["workspace_id"] = cfg.workspace_id
        self.store.put_model(payload)
        self._runs[model_id] = {"backtest": bt, "ic": ic, "dataset_cfg": True}
        if meter:
            meter(cfg.workspace_id, "research_jobs", 1, ref=model_id)
        logger.info("trained %s: IC=%.4f IR=%.2f", model_id, ic["ic"],
                    bt["information_ratio"])
        return rec

    def run_result(self, model_id: str) -> dict:
        return self._runs.get(model_id, {})

    # ---------- validation (Layer C) ----------
    def validate(self, cfg: WorkspaceConfig, model_id: str,
                 gates: Optional[dict[str, float]] = None,
                 meter=None) -> ValidationResult:
        """Gates on OOS IC/IR/DD/turnover + walk-forward stability + overfit flags."""
        gates = {**DEFAULT_GATES, **(gates or {})}
        run = self.run_result(model_id)
        if not run:
            raise RuntimeError(
                f"no research run in memory for {model_id}; re-run research first")
        bt, ic = run["backtest"], run["ic"]
        instruments = cfg.universe or cfg.instruments
        wf = self.engine.walk_forward(
            cfg.factor_set, instruments, cfg.model_type, cfg.hyperparameters,
            cfg.handler_range[0], cfg.handler_range[1],
            n_splits=int(gates["wf_splits"]),
            recorder_dir=os.path.join(self.artifact_root, "mlruns", cfg.workspace_id))
        if meter:
            meter(cfg.workspace_id, "research_jobs", len(wf), ref=model_id)

        icirs = [f["ic"] for f in wf if np.isfinite(f["ic"])]
        ic_std = float(np.std(icirs)) if len(icirs) > 1 else 0.0
        sign_flips = sum(1 for a, b in zip(icirs, icirs[1:]) if a * b < 0)
        # degradation: later folds (further from the fit window) vs first
        # out-of-sample decay: only a *drop* from fold 1 to the last fold is
        # degradation; improvement is fine.
        degradation = (max(0.0, (icirs[0] - icirs[-1]) / abs(icirs[0]))
                       if icirs and icirs[0] else 0.0)

        flags: list[str] = []
        if not np.isfinite(ic["ic"]) or abs(ic["ic"]) < gates["min_ic"]:
            flags.append(f"weak OOS IC {ic['ic']:.3f}")
        if ic["rank_ic"] < 0:
            flags.append("negative rank IC")
        if abs(bt["information_ratio"]) < gates["min_ir"]:
            flags.append(f"IR {bt['information_ratio']:.2f} below gate")
        if len(icirs) >= 2:
            if ic_std > gates["max_ic_std"]:
                flags.append(f"walk-forward IC unstable (std {ic_std:.3f})")
            if sign_flips:
                flags.append(f"{sign_flips} sign flips across folds")
            if abs(degradation) > gates["max_degradation"]:
                flags.append(f"fold degradation {degradation:.0%}")
        if bt["mean_turnover"] > gates["max_turnover"]:
            flags.append(f"turnover {bt['mean_turnover']:.2f}/day exceeds gate")
        if (bt["mean_cost"] > 0 and abs(bt["mean_return"]) > 0
                and bt["mean_cost"] / abs(bt["mean_return"]) > 0.5):
            flags.append("cost consumes >50% of mean return — fragile backtest")
        sens: dict[str, float] = {}
        if gates.get("param_sensitivity"):
            sens = self._param_sensitivity(cfg)
            if sens.get("ic_spread", 0) > gates["max_ic_std"]:
                flags.append("hyperparameter sensitivity: IC collapses off-tuned point")

        metrics = {"ic": ic["ic"], "rank_ic": ic["rank_ic"], "n_oos": ic["n"],
                   "ann_return": bt["ann_return"],
                   "information_ratio": bt["information_ratio"],
                   "max_drawdown": bt["max_drawdown"],
                   "mean_turnover": bt["mean_turnover"],
                   "mean_cost": bt["mean_cost"]}
        gate_results = {
            "min_ic": metrics["ic"] >= gates["min_ic"],
            "min_ir": abs(metrics["information_ratio"]) >= gates["min_ir"],
            "max_dd": metrics["max_drawdown"] >= gates["min_maxdd"],
            "turnover": metrics["mean_turnover"] <= gates["max_turnover"],
            "wf_stable": not any(("unstable" in f) or ("sign flips" in f)
                                 or ("degradation" in f) for f in flags),
        }
        passed = all(gate_results.values()) and not flags
        status = ModelStatus.VALIDATED if passed else ModelStatus.REJECTED
        existing = self.store.get_model(model_id) or {}
        self.store.put_model({**existing, "model_id": model_id,
                              "status": status.value,
                              "validation": ValidationResult(
                                  model_id=model_id, passed=passed, metrics=metrics,
                                  walk_forward=wf, overfit_flags=flags,
                                  stability={"ic_std": ic_std,
                                             "sign_flips": sign_flips,
                                             "degradation": degradation},
                                  sensitivity=sens,
                                  gate_results=gate_results).to_dict()})
        return ValidationResult(
            model_id=model_id, passed=passed, metrics=metrics, walk_forward=wf,
            overfit_flags=flags,
            stability={"ic_std": ic_std, "sign_flips": sign_flips,
                       "degradation": degradation},
            sensitivity=sens, gate_results=gate_results)

    def _param_sensitivity(self, cfg: WorkspaceConfig) -> dict[str, float]:
        """Layer C sensitivity check: retrain ±50% perturbations of key params."""
        base_hp = dict(cfg.hyperparameters or {})
        instruments = cfg.universe or cfg.instruments
        ds = self.engine.build_dataset(cfg.factor_set, instruments,
                                       cfg.handler_range, cfg.fit_range,
                                       cfg.train_segments)
        ics = []
        for k in ("num_leaves", "learning_rate"):
            if k not in base_hp:
                continue
            for mult in (0.5, 2.0):
                hp = dict(base_hp)
                v = hp[k] * mult
                hp[k] = max(1, int(v)) if isinstance(base_hp[k], int) else v
                m = self.engine.build_model(cfg.model_type, hp)
                pred, _ = self.engine.train(m, ds, "sensitivity", "mlruns")
                ics.append(self.engine.ic(ds, pred)["ic"])
        return {"ic_spread": float(np.max(ics) - np.min(ics)) if len(ics) > 1 else 0.0}

    def retrain(self, cfg: WorkspaceConfig, meter=None) -> ModelRecord:
        return self.train(cfg, meter=meter)

"""Load-bearing qlib adapter (Layer B research engine).

This module is the ONLY place UnlockAid talks to qlib. Every research job, backtest,
and daily inference flows through here, so the asset sits in the primary execution
path (Playbook Amendment A.3): there is no fallback implementation of factor
engineering, model training, or backtesting anywhere in this codebase.

If qlib cannot be initialized or executed, `QlibExecutionError` is raised — the
platform fails safely (§24) rather than producing synthetic numbers.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("unlockaid.qlib_engine")

DEFAULT_PROVIDER_URI = os.path.expanduser("~/.qlib/qlib_data/cn_data")


class QlibExecutionError(RuntimeError):
    """Raised when a mandated qlib operation cannot execute. Never silently degraded."""


def _import_qlib():
    try:
        import qlib  # noqa: F401
    except ImportError as e:  # pragma: no cover - environment failure
        raise QlibExecutionError(
            "qlib is not importable. Install with `uv pip install -e /root/repos/qlib`."
        ) from e
    return qlib


@dataclass
class QlibEngine:
    """Owns one qlib session and exposes research primitives as project contracts."""

    provider_uri: str = DEFAULT_PROVIDER_URI
    region: str = "cn"
    initialized: bool = False
    _config: dict = field(default_factory=dict, repr=False)

    # ---------- lifecycle ----------
    def init(self) -> None:
        if self.initialized:
            return
        qlib = _import_qlib()
        if not os.path.isdir(os.path.expanduser(self.provider_uri)):
            raise QlibExecutionError(
                f"qlib data provider_uri missing: {self.provider_uri}. "
                "Run `unlockaid data refresh` to download the qlib binary dump.")
        os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        from qlib.constant import REG_CN, REG_US
        region = REG_CN if self.region == "cn" else REG_US
        qlib.init(provider_uri=self.provider_uri, region=region)
        self.initialized = True
        logger.info("qlib initialized: version=%s uri=%s region=%s",
                    qlib.__version__, self.provider_uri, self.region)

    # ---------- Layer A data reads (real qlib expression engine) ----------
    def features(self, instruments: list[str], expressions: list[str],
                 start_time: str, end_time: str) -> pd.DataFrame:
        self.init()
        from qlib.data import D
        try:
            df = D.features(instruments, expressions,
                            start_time=start_time, end_time=end_time)
        except Exception as e:
            raise QlibExecutionError(f"qlib D.features failed: {e}") from e
        if df is None or df.empty:
            raise QlibExecutionError(
                f"qlib returned no rows for {instruments[:3]}... "
                f"{start_time}..{end_time} — universe/date mismatch?")
        return df

    def calendar(self, start_time: Optional[str] = None,
                 end_time: Optional[str] = None) -> list:
        self.init()
        from qlib.data import D
        return list(D.calendar(start_time=start_time, end_time=end_time))

    def list_instruments(self, universe: str, start_time: str,
                         end_time: str) -> list[str]:
        self.init()
        from qlib.data import D
        try:
            insts = D.list_instruments(D.instruments(market=universe),
                                       start_time=start_time, end_time=end_time,
                                       as_list=True)
        except Exception as e:
            raise QlibExecutionError(f"qlib instruments({universe}) failed: {e}") from e
        return list(insts)

    # ---------- Layer B research: dataset + model + backtest ----------
    def build_dataset(self, factor_set: str, instruments: str | list[str],
                      handler_range: list[str], fit_range: list[str],
                      segments: dict[str, list[str]]) -> Any:
        """Alpha158/Alpha360 handler + DatasetH — qlib's factor/feature stack."""
        self.init()
        from qlib.utils import init_instance_by_config
        handler = {
            "class": factor_set,
            "module_path": "qlib.contrib.data.handler",
            "kwargs": {
                "start_time": handler_range[0],
                "end_time": handler_range[1],
                "fit_start_time": fit_range[0],
                "fit_end_time": fit_range[1],
                "instruments": instruments,
            },
        }
        try:
            return init_instance_by_config({
                "class": "DatasetH",
                "module_path": "qlib.data.dataset",
                "kwargs": {"handler": handler, "segments": segments},
            })
        except Exception as e:
            raise QlibExecutionError(f"qlib dataset ({factor_set}) build failed: {e}") from e

    def build_custom_factor_dataset(self, expressions: list[str], names: list[str],
                                    instruments: str | list[str], label_exprs: list[str],
                                    handler_range: list[str], fit_range: list[str],
                                    segments: dict[str, list[str]]) -> Any:
        """Factor-mining entry point: arbitrary qlib expression strings become features."""
        self.init()
        from qlib.utils import init_instance_by_config
        handler = {
            "class": "DataHandlerLP",
            "module_path": "qlib.data.dataset.handler",
            "kwargs": {
                "instruments": instruments,
                "start_time": handler_range[0],
                "end_time": handler_range[1],
                "data_loader": {
                    "class": "QlibDataLoader",
                    "module_path": "qlib.data.dataset.loader",
                    "kwargs": {"config": {
                        "feature": (expressions, names),
                        "label": (label_exprs, ["LABEL0"]),
                    }},
                },
                "infer_processors": [
                    {"class": "DropnaLabel", "kwargs": {}},
                    {"class": "RobustZScoreNorm",
                     "kwargs": {"fields_group": "feature",
                                "clip_outlier": True,
                                "fit_start_time": fit_range[0],
                                "fit_end_time": fit_range[1]}},
                    {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
                ],
            },
        }
        try:
            return init_instance_by_config({
                "class": "DatasetH", "module_path": "qlib.data.dataset",
                "kwargs": {"handler": handler, "segments": segments}})
        except Exception as e:
            raise QlibExecutionError(f"qlib custom factor dataset failed: {e}") from e

    _MODEL_CLASSES = {
        "lightgbm": ("LGBModel", "qlib.contrib.model.gbdt"),
        "linear": ("LinearModel", "qlib.contrib.model.linear"),
        "ridge": ("LinearModel", "qlib.contrib.model.linear"),
        "lasso": ("LinearModel", "qlib.contrib.model.linear"),
        "catboost": ("CatBoostModel", "qlib.contrib.model.catboost_model"),
        "xgboost": ("XGBModel", "qlib.contrib.model.xgboost"),
        "gru": ("PyTorchGRUModel", "qlib.contrib.model.pytorch_gru"),
        "lstm": ("PyTorchLSTMModel", "qlib.contrib.model.pytorch_lstm"),
    }

    def build_model(self, model_type: str, hyperparameters: dict[str, Any]) -> Any:
        self.init()
        from qlib.utils import init_instance_by_config
        if model_type not in self._MODEL_CLASSES:
            raise QlibExecutionError(
                f"unsupported model_type {model_type!r}; qlib provides "
                f"{sorted(self._MODEL_CLASSES)} (34 models in qlib.contrib.model)")
        cls, mod = self._MODEL_CLASSES[model_type]
        kwargs = dict(hyperparameters)
        if model_type in ("ridge", "lasso"):
            kwargs.setdefault("estimator", model_type)
        try:
            return init_instance_by_config({"class": cls, "module_path": mod,
                                            "kwargs": kwargs})
        except Exception as e:
            raise QlibExecutionError(f"qlib model {model_type} init failed: {e}") from e

    def train(self, model: Any, dataset: Any, experiment_name: str,
              recorder_dir: str) -> tuple[np.ndarray, dict[str, Any]]:
        """Fit + score via qlib's Model API; records the experiment with qlib workflow."""
        self.init()
        import qlib
        from qlib.workflow import R
        try:
            os.makedirs(recorder_dir, exist_ok=True)
            qlib.init(provider_uri=self.provider_uri, region=self.region)
            with R.start(experiment_name=experiment_name, recorder_id=None):
                R.log_params(**{"engine": "qlib", "model": type(model).__name__})
                model.fit(dataset)
                valid_pred = model.predict(dataset, segment="valid")
                test_pred = model.predict(dataset, segment="test")
                rec = R.get_recorder()
                rec_id = rec.id
                for seg, p in (("valid", valid_pred), ("test", test_pred)):
                    if p is not None and len(p):
                        R.log_metrics(**{f"{seg}_n_predictions": int(len(p))})
        except Exception as e:
            raise QlibExecutionError(f"qlib training failed: {e}") from e
        meta = {"recorder_id": rec_id, "experiment_name": experiment_name,
                "model_class": type(model).__name__}
        return test_pred, meta

    def ic(self, dataset: Any, pred: pd.Series, segment: str = "test") -> dict[str, float]:
        """Information coefficient — computed on qlib-prepared labels."""
        label = dataset.prepare(segment, col_set="label")["LABEL0"]
        s = pred.reindex(label.index)
        mask = label.notna() & s.notna()
        if mask.sum() < 10:
            return {"ic": float("nan"), "rank_ic": float("nan"), "n": int(mask.sum())}
        y, x = label[mask].to_numpy(), s[mask].to_numpy()
        ic = float(np.corrcoef(x, y)[0, 1])
        rank_ic = float(pd.Series(x).corr(pd.Series(y), method="spearman"))
        return {"ic": ic, "rank_ic": rank_ic, "n": int(mask.sum())}

    def save_model(self, model: Any, path: str) -> str:
        import dill
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            dill.dump(model, f)
        return path

    def load_model(self, path: str, model_type: str) -> Any:
        import dill
        if not os.path.exists(path):
            raise QlibExecutionError(f"model artifact missing: {path}")
        with open(path, "rb") as f:
            return dill.load(f)

    def predict_latest(self, model: Any, dataset: Any,
                       segment: str = "latest") -> pd.Series:
        """Daily inference (Layer E→F): qlib predict on the freshest segment."""
        try:
            return model.predict(dataset, segment=segment)
        except Exception as e:
            raise QlibExecutionError(f"qlib inference failed: {e}") from e

    def backtest(self, signal: pd.Series, start_time: str, end_time: str,
                 topk: int = 50, n_drop: int = 5, account: float = 1_000_000,
                 benchmark: str = "SH000300",
                 exchange_kwargs: Optional[dict] = None) -> dict[str, Any]:
        """Run qlib's real backtest engine (TopkDropout + SimulatorExecutor)."""
        self.init()
        from qlib.contrib.strategy import TopkDropoutStrategy
        from qlib.backtest import backtest as qlib_backtest
        from qlib.contrib.evaluate import risk_analysis
        sig = signal.dropna()
        if sig.empty:
            raise QlibExecutionError("backtest received an all-NaN signal")
        strategy = TopkDropoutStrategy(signal=sig, topk=topk, n_drop=n_drop)
        ex = {"class": "SimulatorExecutor", "module_path": "qlib.backtest.executor",
              "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True}}
        try:
            pm, _ind = qlib_backtest(start_time=start_time, end_time=end_time,
                                     strategy=strategy, executor=ex, account=account,
                                     benchmark=benchmark,
                                     exchange_kwargs=exchange_kwargs or {})
        except Exception as e:
            raise QlibExecutionError(f"qlib backtest failed: {e}") from e
        if not pm:
            raise QlibExecutionError("qlib backtest produced no portfolio metrics")
        freq = list(pm.keys())[0]
        report = pm[freq][0]
        excess = report["return"] - report["bench"]
        ra = risk_analysis(excess).iloc[:, 0].to_dict()
        return {
            "freq": str(freq),
            "dates": [d.strftime("%Y-%m-%d") for d in report.index],
            "returns": [float(v) for v in report["return"].to_numpy()],
            "benchmark_returns": [float(v) for v in report["bench"].to_numpy()],
            "costs": [float(v) for v in report["cost"].to_numpy()],
            "turnovers": [float(v) for v in report["turnover"].to_numpy()],
            "ann_return": float(ra["annualized_return"]),
            "information_ratio": float(ra["information_ratio"]),
            "max_drawdown": float(ra["max_drawdown"]),
            "mean_return": float(ra["mean"]),
            "std_return": float(ra["std"]),
            "mean_turnover": float(np.mean(report["turnover"].to_numpy())),
            "mean_cost": float(np.mean(report["cost"].to_numpy())),
            "engine_source": "qlib",
        }

    def walk_forward(self, factor_set: str, instruments: str | list[str],
                     model_type: str, hyperparameters: dict,
                     start: str, end: str, n_splits: int = 3,
                     recorder_dir: str = "mlruns") -> list[dict[str, Any]]:
        """Expanding-window walk-forward: train on all history, test on the next
        contiguous block. Real overfitting defense (Layer C / §3)."""
        self.init()
        cal = [d.strftime("%Y-%m-%d") for d in self.calendar(start, end)]
        if len(cal) < n_splits + 20:
            raise QlibExecutionError("not enough calendar days for walk-forward")
        # reserve the last 60% of the window for out-of-sample folds
        anchor = int(len(cal) * 0.4)
        blocks = np.linspace(anchor, len(cal) - 1, n_splits + 1).astype(int)
        folds: list[dict[str, Any]] = []
        for i in range(n_splits):
            tr_end, te_start, te_end = blocks[i], blocks[i], blocks[i + 1]
            segments = {
                "train": [cal[0], cal[tr_end]],
                "valid": [cal[max(0, tr_end - 10)], cal[tr_end]],
                "test": [cal[te_start + 1], cal[te_end]],
            }
            ds = self.build_dataset(factor_set, instruments, [start, end],
                                    [start, segments["train"][1]], segments)
            model = self.build_model(model_type, hyperparameters)
            pred, meta = self.train(model, ds,
                                    f"walk-forward-{i}", recorder_dir)
            stats = self.ic(ds, pred, "test")
            folds.append({"fold": i, "train": segments["train"],
                          "test": segments["test"], "recorder_id": meta["recorder_id"],
                          **stats})
            logger.info("walk-forward fold %d (%s..%s): IC=%.4f",
                        i, *segments["test"], stats["ic"])
        return folds

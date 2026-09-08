#!/usr/bin/env python
"""Phase-1 asset smoke test: prove qlib runs inside this project environment.

Loads real features via qlib's data layer, trains a real qlib LightGBM model on
Alpha158 factors over CSI300, scores out-of-sample, and runs a qlib backtest.
Output is captured into docs/BUILD_EVIDENCE.md.
"""
import time

import numpy as np
import pandas as pd
import qlib
from qlib.constant import REG_CN
from qlib.contrib.model.gbdt import LGBModel
from qlib.contrib.strategy import TopkDropoutStrategy
from qlib.backtest import backtest
import os
from qlib.contrib.evaluate import risk_analysis
from qlib.utils import init_instance_by_config

t0 = time.time()
qlib.init(provider_uri="~/.qlib/qlib_data/cn_data", region=REG_CN)
print(f"qlib.init OK in {time.time()-t0:.1f}s, version={qlib.__version__}")

# 1. data layer: real feature read through qlib's expression engine
from qlib.data import D
df = D.features(["SH600519", "SZ000001", "SH601318"], ["$close", "$volume"],
                start_time="2026-06-01", end_time="2026-09-04")
print(f"D.features OK: {df.shape[0]} rows, last close SH600519="
      f"{df.xs('SH600519').tail(1)['$close'].item():.2f}")

# 2. Alpha158 factor handler + DatasetH (the standard qlib research stack)
handler_config = {
    "class": "Alpha158",
    "module_path": "qlib.contrib.data.handler",
    "kwargs": {
        "start_time": "2025-01-01",
        "end_time": "2026-09-04",
        "fit_start_time": "2025-01-01",
        "fit_end_time": "2026-03-01",
        "instruments": "csi300",
    },
}
dataset_config = {
    "class": "DatasetH",
    "module_path": "qlib.data.dataset",
    "kwargs": {
        "handler": handler_config,
        "segments": {
            "train": ["2025-01-01", "2026-03-31"],
            "valid": ["2026-04-01", "2026-05-05"],
            "test": ["2026-05-06", "2026-09-04"],
        },
    },
}
dataset = init_instance_by_config(dataset_config)
print("DatasetH(Alpha158/csi300) OK:", {k: len(v) for k, v in dataset.segments.items()})

# 3. model train via qlib LGBModel
model = LGBModel(loss="mse", learning_rate=0.05, num_leaves=64, colsample_bytree=0.88,
                 subsample=0.88, num_boost_round=200, early_stopping_rounds=50, n_jobs=8)
model.fit(dataset)
pred = model.predict(dataset, segment="test")
label = dataset.prepare("test", col_set="label")["LABEL0"]
mask = label.notna() & pred.notna()
ic = float(np.corrcoef(pred[mask], label[mask])[0, 1])
test_dates = pred.index.get_level_values("datetime")
print(f"LGBModel train OK, test IC={ic:.4f} over {len(pred)} samples "
      f"({test_dates.min().date()}..{test_dates.max().date()})")

# 4. backtest via qlib engine (topk-dropout, 1-day step, CSI300 benchmark)
strategy = TopkDropoutStrategy(signal=pred, topk=30, n_drop=3)
pm, _ = backtest(start_time="2026-05-06", end_time="2026-09-04",
                 strategy=strategy, account=1000000, benchmark="SH000300",
                 executor={"class": "SimulatorExecutor", "module_path": "qlib.backtest.executor",
                           "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True}})
freq = list(pm.keys())[0]
report = pm[freq][0]
ra = risk_analysis(report["return"] - report["bench"]).iloc[:, 0]
print(f"backtest OK: excess ann.return={ra['annualized_return']:.2%}, "
      f"IR={ra['information_ratio']:.2f}, maxdd={ra['max_drawdown']:.2%}")
print(f"SMOKE_OK total {time.time()-t0:.0f}s")

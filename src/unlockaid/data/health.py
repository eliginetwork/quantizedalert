"""Layer A — data acquisition, refresh, and health detection.

Detects: missing data, stale data, anomalous values, pipeline failures,
unexpected changes (objective §5 Layer A). All reads go through the qlib
engine adapter; this module never synthesizes prices.
"""
from __future__ import annotations

import logging
import os
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from unlockaid.engine.qlib_engine import QlibEngine, QlibExecutionError
from unlockaid.schemas import AssetHealth, DataHealthReport, DataHealthStatus

logger = logging.getLogger("unlockaid.data")

QLIB_DUMP_URL = ("https://github.com/chenditc/investment_data/releases/"
                 "latest/download/qlib_bin.tar.gz")
MAX_STALE_DAYS = 4          # trading days before a bar is 'stale'
ANOMALY_Z = 6.0             # return z-score anomaly threshold
ANOMALY_ABS_PCT = 0.21      # daily move beyond exchange limits
VOLUME_Z = 12.0


def refresh_dump(provider_uri: str, url: str = QLIB_DUMP_URL,
                 force: bool = False, session=None) -> dict:
    """Class 4 asset: download + extract the open qlib daily-bar dump.

    Idempotent unless force. Returns size/status info for metering.
    """
    marker = os.path.join(provider_uri, "calendars", "day.txt")
    if os.path.exists(marker) and not force:
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(
            os.path.getmtime(marker), timezone.utc)
        if age < timedelta(days=1):
            return {"status": "fresh", "age_days": age.days, "path": provider_uri}
    import requests
    sess = session or requests
    tmp = tempfile.mktemp(suffix=".tar.gz")
    try:
        logger.info("downloading qlib data dump -> %s", tmp)
        with sess.get(url, stream=True, timeout=600, allow_redirects=True) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                nbytes = 0
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    nbytes += len(chunk)
        os.makedirs(provider_uri, exist_ok=True)
        with tarfile.open(tmp, "r:gz") as t:
            t.extractall(provider_uri)  # archive root = calendars/features/instruments
        return {"status": "refreshed", "bytes": nbytes, "path": provider_uri}
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def check_health(engine: QlibEngine, universe: str, instruments: list[str],
                 lookback_days: int = 30) -> DataHealthReport:
    """Health-check the last `lookback_days` of bars per instrument via qlib data."""
    cal = engine.calendar()
    last = pd.Timestamp(cal[-1]).strftime("%Y-%m-%d")
    start = pd.Timestamp(cal[-(lookback_days + 1)]).strftime("%Y-%m-%d")
    df = engine.features(instruments,
                         ["$close", "$volume", "Ref($close, 1)", "Ref($volume, 1)"],
                         start, last)
    df.columns = ["close", "volume", "prev_close", "prev_volume"]
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assets: list[AssetHealth] = []
    failed: list[str] = []
    per_inst: dict[str, pd.DataFrame] = {}
    cal_arr = np.array(cal, dtype="datetime64[D]")
    last_pos = int(np.searchsorted(cal_arr, np.datetime64(last)))
    for inst, g in df.groupby(level="instrument"):
        per_inst[inst] = g.droplevel("instrument").sort_index()

    for inst in instruments:
        if inst not in per_inst or per_inst[inst].empty:
            assets.append(AssetHealth(inst, None, DataHealthStatus.MISSING,
                                      staleness_days=999, engine_source="qlib"))
            failed.append(inst)
            continue
        g = per_inst[inst]
        last_bar = g.index[-1].strftime("%Y-%m-%d")
        stale = max(0, last_pos - int(np.searchsorted(cal_arr, np.datetime64(last_bar))))
        anomalies: list[str] = []
        ret = (g["close"] / g["prev_close"] - 1).dropna()
        if len(ret) > 5:
            z = (ret.iloc[-1] - ret.mean()) / (ret.std() + 1e-12)
            if abs(ret.iloc[-1]) > ANOMALY_ABS_PCT:
                anomalies.append(f"daily_move_{ret.iloc[-1]:+.1%}")
            elif abs(z) > ANOMALY_Z:
                anomalies.append(f"return_zscore_{z:+.1f}")
        vol = (g["volume"] / g["prev_volume"]).dropna()
        if len(vol) > 5:
            vz = (np.log(vol.iloc[-1]) - np.log(vol).mean()) / (np.log(vol).std() + 1e-12)
            if vz > VOLUME_Z:
                anomalies.append(f"volume_spike_z{vz:.1f}")
        if g["close"].isna().mean() > 0.1:
            anomalies.append("missing_values")
        status = (DataHealthStatus.ANOMALY if anomalies else
                  DataHealthStatus.STALE if stale > MAX_STALE_DAYS else
                  DataHealthStatus.OK)
        assets.append(AssetHealth(inst, last_bar, status, stale, anomalies,
                                  engine_source="qlib"))
    report = DataHealthReport(
        checked_at=now_iso, universe=universe, calendar_last=last,
        fresh=stale_ok(cal), assets=assets, failed=failed)
    return report


def stale_ok(cal: list) -> bool:
    """True if calendar's last bar is within 5 days of today."""
    if not cal:
        return False
    last = pd.Timestamp(str(cal[-1]))
    return (pd.Timestamp.now() - last).days <= 5

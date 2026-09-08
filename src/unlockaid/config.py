"""UnlockAid configuration: platform config + per-workspace config.

`config/platform.yaml` holds engine paths + service settings.
`config/workspaces/<id>.yaml` holds customer-facing config: universe, research
workflow, portfolio, alert preferences (thresholds, quiet hours, channels).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class PlatformConfig:
    qlib_provider_uri: str = os.environ.get(
        "UNLOCKAID_QLIB_URI", str(Path.home() / ".qlib/qlib_data/cn_data"))
    qlib_region: str = "cn"
    dsa_path: str = os.environ.get("DSA_PATH", "/root/repos/daily_stock_analysis")
    qlib_path: str = os.environ.get("QLIB_PATH", "/root/repos/qlib")
    mlflow_allow_file_store: bool = True
    db_path: str = str(ROOT / "data" / "unlockaid.db")
    artifact_dir: str = str(ROOT / "data" / "artifacts")
    workspace_dir: str = str(ROOT / "config" / "workspaces")
    data_dir: str = str(ROOT / "data")
    # research defaults
    train_n_jobs: int = 8
    num_boost_round: int = 200

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "PlatformConfig":
        p = path or (ROOT / "config" / "platform.yaml")
        if p.exists():
            raw = yaml.safe_load(p.read_text()) or {}
            known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
            return cls(**known)
        return cls()


@dataclass
class AlertPrefs:
    min_score: float = 0.45            # alert intelligence delivery threshold
    max_alerts_per_day: int = 5        # "fewer, higher-value alerts" (§7)
    quiet_hours: list[str] = field(default_factory=lambda: ["23:00", "07:00"])
    quiet_hours_tz: str = "Asia/Shanghai"
    channels: list[str] = field(default_factory=lambda: ["custom_webhook"])
    routes: dict[str, str] = field(default_factory=dict)   # kind -> DSA route_type
    min_severity: str = "low"
    dedup_window_hours: int = 24


@dataclass
class WorkspaceConfig:
    workspace_id: str
    name: str = ""
    plan: str = "free"
    universe: str = "csi300"
    instruments: list[str] = field(default_factory=list)
    watchlist: list[str] = field(default_factory=list)
    portfolio: list[dict[str, float]] = field(default_factory=list)  # [{instrument, weight}]
    region: str = "cn"
    # research
    factor_set: str = "Alpha158"
    model_type: str = "lightgbm"
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    train_segments: dict[str, list[str]] = field(default_factory=lambda: {
        "train": ["2025-01-01", "2026-03-31"],
        "valid": ["2026-04-01", "2026-05-05"],
        "test": ["2026-05-06", "2026-09-04"]})
    handler_range: list[str] = field(default_factory=lambda: ["2025-01-01", "2026-09-04"])
    fit_range: list[str] = field(default_factory=lambda: ["2025-01-01", "2026-03-01"])
    # backtest
    backtest: dict[str, Any] = field(default_factory=lambda: {
        "topk": 30, "n_drop": 3, "account": 1000000, "benchmark": "SH000300"})
    # deploy
    schedule_time: str = "17:30"
    alerts: AlertPrefs = field(default_factory=AlertPrefs)

    @classmethod
    def load(cls, path: Path) -> "WorkspaceConfig":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        ap = raw.pop("alerts", {}) or {}
        known = {k: v for k, v in ap.items() if k in AlertPrefs.__dataclass_fields__}
        wc_fields = set(cls.__dataclass_fields__)
        cleaned = {k: v for k, v in raw.items() if k in wc_fields}
        return cls(alerts=AlertPrefs(**known), **cleaned)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        from dataclasses import asdict
        d = asdict(self)
        path.write_text(yaml.safe_dump(d, sort_keys=False, allow_unicode=True))

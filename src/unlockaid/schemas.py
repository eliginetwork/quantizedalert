"""Domain contracts (schemas) shared across UnlockAid layers.

Every artifact that crosses a layer boundary is one of these. `engine_source`
fields implement Playbook Amendment E (fallback transparency): the value records
which engine actually produced the data ("qlib", "daily_stock_analysis", or a
named fallback); `degraded` paths must say so.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {Severity.CRITICAL: 5, Severity.HIGH: 4, Severity.MEDIUM: 3,
                Severity.LOW: 2, Severity.INFO: 1}[self]


class ModelStatus(str, Enum):
    CANDIDATE = "candidate"        # trained, not validated
    VALIDATED = "validated"        # passed validation gates
    REJECTED = "rejected"          # failed validation (overfit/unstable)
    DEPLOYED = "deployed"          # scheduled for daily inference
    RETIRED = "retired"


class DataHealthStatus(str, Enum):
    OK = "ok"
    STALE = "stale"
    MISSING = "missing"
    ANOMALY = "anomaly"


@dataclass
class AssetHealth:
    """Layer A: health verdict for one instrument's data."""
    instrument: str
    last_bar: Optional[str]
    status: DataHealthStatus
    staleness_days: int
    anomalies: list[str] = field(default_factory=list)
    engine_source: str = "qlib"


@dataclass
class DataHealthReport:
    checked_at: str
    universe: str
    calendar_last: Optional[str]
    fresh: bool
    assets: list[AssetHealth]
    failed: list[str] = field(default_factory=list)  # pipeline failures
    engine_source: str = "qlib"

    @property
    def anomaly_count(self) -> int:
        return sum(1 for a in self.assets if a.status is DataHealthStatus.ANOMALY)

    @property
    def stale_count(self) -> int:
        return sum(1 for a in self.assets
                   if a.status in (DataHealthStatus.STALE, DataHealthStatus.MISSING))


@dataclass
class BacktestReport:
    """Layer B output — normalized from qlib's report DataFrame."""
    freq: str
    dates: list[str]
    returns: list[float]
    benchmark_returns: list[float]
    costs: list[float]
    turnovers: list[float]
    # headline stats (qlib.contrib.evaluate.risk_analysis on excess return)
    ann_return: float
    mean_return: float
    std_return: float
    information_ratio: float
    max_drawdown: float
    mean_turnover: float
    mean_cost: float
    engine_source: str = "qlib"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationResult:
    """Layer C verdict."""
    model_id: str
    passed: bool
    metrics: dict[str, float]          # ic, rank_ic, ann_return, ir, maxdd, turnover…
    walk_forward: list[dict[str, float]] = field(default_factory=list)
    overfit_flags: list[str] = field(default_factory=list)
    stability: dict[str, float] = field(default_factory=dict)
    sensitivity: dict[str, float] = field(default_factory=dict)
    gate_results: dict[str, bool] = field(default_factory=dict)
    engine_source: str = "qlib+unlockaid"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ModelRecord:
    """Layer D registry row."""
    model_id: str
    name: str
    version: str
    status: ModelStatus
    dataset_ref: str                   # e.g. "Alpha158/csi300/2025-01-01..2026-09-04"
    factor_set: str
    hyperparameters: dict[str, Any]
    experiment_ref: Optional[str]      # qlib workflow recorder id (lineage!)
    artifact_path: Optional[str]
    validation: Optional[dict]
    created_at: str
    created_by: str = "research-agent"
    engine_source: str = "qlib"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class Prediction:
    """Layer E/F handoff: one scored instrument for one business date."""
    instrument: str
    asof: str
    model_id: str
    score: float
    rank: int
    workspace_id: str


@dataclass
class SignalChange:
    """Layer F: change vs previous day for the watchlist."""
    instrument: str
    asof: str
    previous_rank: Optional[int]
    rank: int
    previous_score: Optional[float]
    score: float
    rank_delta: Optional[int]
    price: Optional[float] = None
    price_change_pct: Optional[float] = None


@dataclass
class AlertEvent:
    """Layer G input event before prioritization."""
    event_id: str
    workspace_id: str
    kind: str            # model_drift | data_stale | signal_change | risk_breach | regime | job_failure | anomaly
    title: str
    body_md: str         # markdown rendered for delivery
    severity: Severity
    instruments: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    score: float = 0.0   # computed by alert intelligence
    components: dict[str, float] = field(default_factory=dict)
    created_at: str = ""
    dedup_key: str = ""
    route_type: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class AlertDecision:
    event: AlertEvent
    deliver: bool
    suppress_reason: Optional[str] = None
    channels: list[str] = field(default_factory=list)
    delivered: dict[str, bool] = field(default_factory=dict)
    engine_source: str = "unlockaid+daily_stock_analysis"


@dataclass
class DailyRunResult:
    """The customer-facing bundle for one workspace-day."""
    workspace_id: str
    asof: str
    ok: bool
    data_health: Optional[DataHealthReport]
    predictions: list[Prediction]
    changes: list[SignalChange]
    portfolio: dict[str, Any]
    alerts: list[AlertDecision]
    model_id: str
    error: Optional[str] = None
    engine_sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "workspace_id": self.workspace_id,
            "asof": self.asof,
            "ok": self.ok,
            "model_id": self.model_id,
            "error": self.error,
            "data_health": _health_dict(self.data_health) if self.data_health else None,
            "predictions": [asdict(p) for p in self.predictions[:20]],
            "n_predictions": len(self.predictions),
            "changes": [asdict(c) for c in self.changes[:20]],
            "portfolio": self.portfolio,
            "alerts": [_alert_decision_dict(a) for a in self.alerts],
            "engine_sources": self.engine_sources,
        }


def _health_dict(h: DataHealthReport) -> dict:
    d = asdict(h)
    d["anomaly_count"] = h.anomaly_count
    d["stale_count"] = h.stale_count
    d["missing_count"] = len(h.failed)
    return d


def _alert_decision_dict(a: AlertDecision) -> dict:
    return {
        "event_id": a.event.event_id,
        "kind": a.event.kind,
        "title": a.event.title,
        "severity": a.event.severity.value,
        "score": round(a.event.score, 3),
        "components": {k: round(v, 3) for k, v in a.event.components.items()},
        "instruments": a.event.instruments,
        "models": a.event.models,
        "deliver": a.deliver,
        "suppress_reason": a.suppress_reason,
        "channels": a.channels,
        "delivered": a.delivered,
        "engine_source": a.engine_source,
    }

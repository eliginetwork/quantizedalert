"""§24 fail-safe + Amendment E contract tests (offline, injected faults).

The engine/alerter are the two integration seams; each fault here has a real
prod trigger (qlib data break, webhook down) and each assertion protects the
revenue claim: never silent zero output, never silent channel failure.
"""
from __future__ import annotations

import pytest

from quantizedalert.alerts.dsa_dispatch import AlertDeliveryError
from quantizedalert.alerts.intelligence import AlertIntelligence
from quantizedalert.analysis.daily import DailyPipeline
from quantizedalert.config import AlertPrefs, WorkspaceConfig
from quantizedalert.engine.qlib_engine import QlibExecutionError
from quantizedalert.schemas import AlertEvent, Severity, new_id
from quantizedalert.store import Store


class BoomEngine:
    """Every qlib call explodes (provider wiped, disk full, bad model blob)."""
    provider_uri = "/nonexistent"

    def calendar(self, *a, **k):
        raise QlibExecutionError("qlib calendar unavailable")

    def features(self, *a, **k):
        raise QlibExecutionError("qlib features unavailable")

    def build_dataset(self, *a, **k):
        raise QlibExecutionError("qlib dataset unavailable")

    def list_instruments(self, *a, **k):
        raise QlibExecutionError("qlib instruments unavailable")

    def load_model(self, *a, **k):
        raise QlibExecutionError("qlib model artifact load failed")


class OkAlerter:
    engine_source = "fake"

    def dispatch(self, md, channels, **k):
        return dict.fromkeys(channels, True)


class DeadAlerter:
    """Channels configured but every send returns False (webhook 500s)."""
    engine_source = "fake-dead"

    def __init__(self):
        self.calls = 0

    def dispatch(self, md, channels, **k):
        self.calls += 1
        return dict.fromkeys(channels, False)


@pytest.fixture()
def ws_cfg(tmp_path):
    return WorkspaceConfig(workspace_id="w1", name="w1", plan="individual",
                           universe="csi300", watchlist=["SH600519"],
                           alerts=AlertPrefs(channels=["custom_webhook"],
                                             max_alerts_per_day=5))


def test_engine_failure_recorded_not_swallowed(tmp_path, ws_cfg):
    store = Store(str(tmp_path / "t.db"))
    store.put_model({"model_id": "m1", "name": "n", "version": "v",
                     "status": "candidate", "dataset_ref": "d",
                     "factor_set": "Alpha158", "hyperparameters": {},
                     "experiment_ref": None, "artifact_path": "/tmp/fake-art",
                     "validation": None, "created_at": "now"})
    store.set_deployment("w1", "m1", True, "17:30")
    pipe = DailyPipeline(BoomEngine(), store,
                         AlertIntelligence(store, OkAlerter(), ws_cfg.alerts))
    res = pipe.run(ws_cfg)
    assert res.ok is False
    assert res.error and "qlib" in res.error.lower()
    run = store.latest_daily_run("w1")
    assert run["ok"] == 0 and run["error"]  # visible to dashboard, not lost


def test_delivery_failure_blocks_claim(tmp_path, ws_cfg):
    """An event whose channels all fail must NOT be delivered/metered True."""
    store = Store(str(tmp_path / "t.db"))
    dead = DeadAlerter()
    ai = AlertIntelligence(store, dead, ws_cfg.alerts)
    e = AlertEvent(new_id("evt"), "w1", "signal_change", "t", "b",
                   Severity.CRITICAL, instruments=["SH600000"],
                   components={"confidence": 1.0, "risk": 1.0,
                               "historical_significance": 1.0})
    d = ai.process([e], "w1", "2026-09-04", {"SH600000"})
    assert d[0].deliver is False
    assert d[0].suppress_reason == "delivery failed on all channels"
    # nothing was recorded as delivered for the day
    assert not any(a["deliver"] for a in store.recent_alerts("w1"))


def test_missing_service_raises_loud():
    a = object.__new__(__import__("quantizedalert.alerts.dsa_dispatch",
                                  fromlist=["DSAlerter"]).DSAlerter)
    a._service = None
    with pytest.raises(AlertDeliveryError):
        a.dispatch("x", ["telegram"])


def test_quiet_hours_rule():
    from quantizedalert.alerts.intelligence import in_quiet_hours
    assert in_quiet_hours(23 * 60 + 30, "22:00", "07:00")   # overnight span
    assert not in_quiet_hours(12 * 60, "22:00", "07:00")
    assert in_quiet_hours(2 * 60, "00:30", "06:00")         # plain range
    assert in_quiet_hours(0, "22:00", "07:00")             # 00:00 is overnight

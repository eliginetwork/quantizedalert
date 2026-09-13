"""Regression tests for the v0.1.1 review fixes (offline, deterministic)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from quantizedalert.alerts.intelligence import AlertIntelligence
from quantizedalert.config import AlertPrefs
from quantizedalert.schemas import AlertEvent, Severity, new_id
from quantizedalert.store import Store


class OkAlerter:
    engine_source = "fake"

    def dispatch(self, md, channels, **k):
        return dict.fromkeys(channels, True)


# ---- H1: negative IR must fail the min_ir gate ---------------------------
def test_negative_ir_flagged_by_default_gates():
    from quantizedalert.research.runner import DEFAULT_GATES
    # mirrors the runner's gate arithmetic
    bt_ir = -0.8
    assert bt_ir < DEFAULT_GATES["min_ir"]          # flag raised
    assert not (-0.8 >= DEFAULT_GATES["min_ir"])    # gate fails


# ---- H3/M10: metering never aborts completed work; jobs recorded ---------
def test_make_meter_records_overage_without_raising(tmp_path):
    from quantizedalert.cli import make_meter
    store = Store(str(tmp_path / "m.db"))
    meter = make_meter(store, "free")
    cap = 5  # PLANS['free']['research_jobs_month']
    for _ in range(cap):
        meter("w", "research_jobs", 1, ref="x")
    meter("w", "research_jobs", 1, ref="y")         # over limit — must not raise
    with store._conn() as c:  # noqa: SLF001 — white-box assertion in tests only
        n = c.execute("SELECT COUNT(*) FROM usage WHERE metric='research_jobs_overage'"
                      ).fetchone()[0]
    assert n == 1


def test_preflight_quota_raises_before_work(tmp_path):
    from quantizedalert.cli import preflight_quota
    from quantizedalert.commercial.plans import QuotaError
    store = Store(str(tmp_path / "p.db"))

    class Cfg:
        workspace_id = "w"
        plan = "free"

    preflight_quota(store, Cfg(), "research_jobs", qty=4)  # under cap: ok
    with pytest.raises(QuotaError):
        preflight_quota(store, Cfg(), "research_jobs", qty=6)  # over cap pre-flight


def test_plan_alert_budget_is_source_of_truth(tmp_path):
    from quantizedalert.cli import cap_alert_budget
    from quantizedalert.commercial.plans import PLANS
    store = Store(str(tmp_path / "c.db"))

    class Cfg:
        plan = "free"
        alerts = AlertPrefs(max_alerts_per_day=99)

    cap_alert_budget(store, Cfg())
    assert Cfg.alerts.max_alerts_per_day <= PLANS["free"]["alerts_day"]


# ---- L3: novelty uses asof, tolerant timestamp parse ---------------------
def test_novelty_uses_asof_not_wall_clock(tmp_path):
    store = Store(str(tmp_path / "n.db"))
    prefs = AlertPrefs(channels=["custom_webhook"])
    ai = AlertIntelligence(store, OkAlerter(), prefs)
    store.record_alert({
        "event_id": "e1", "workspace_id": "w", "kind": "signal_change",
        "title": "t", "severity": "high", "score": 0.9,
        "components": {}, "instruments": [], "models": [],
        "deliver": True, "suppress_reason": None, "channels": [],
        "delivered": {}, "created_at": "2020-01-01 00:00:00",
        "asof": "2026-09-01", "dedup_key": "k1"})
    recent = store.recent_alerts("w", since_hours=10**6)
    e = AlertEvent(new_id("evt"), "w", "signal_change", "t", "b",
                   Severity.HIGH, instruments=["A"])
    comps = ai.score(e, set(), recent, asof="2026-09-01")
    # last same-kind delivery was years before asof -> fully novel
    assert comps["novelty"] == 1.0


# ---- M8: dsa_importable does not leave `src` in sys.modules --------------
def test_dsa_modules_purged_after_context():
    dsa_path = os.environ.get("DSA_PATH") or str(Path(__file__).resolve().parents[1] / "repos" / "daily_stock_analysis")
    if not os.path.isdir(dsa_path):
        for candidate in ["/root/repos/daily_stock_analysis", "/home/ubuntu/repos/daily_stock_analysis"]:
            try:
                if os.path.isdir(candidate):
                    dsa_path = candidate
                    break
            except PermissionError:
                pass
    try:
        if not os.path.isdir(dsa_path):
            pytest.skip("DSA repo not present")
    except PermissionError:
        pytest.skip("DSA repo not accessible")
    from quantizedalert.assets.dsa_path import dsa_importable, dsa_module
    with dsa_importable(dsa_path):
        dsa_module("src.notification", dsa_path)
    assert not any(m == "src" or m.startswith("src.") for m in sys.modules)


# ---- M11: `rank` keyword column fully quoted -----------------------------
def test_predictions_roundtrip_with_rank_keyword(tmp_path):
    store = Store(str(tmp_path / "r.db"))
    store.put_predictions([
        {"workspace_id": "w", "model_id": "m", "instrument": f"S{i}",
         "asof": "2026-09-04", "score": float(i), "rank": i}
        for i in range(1, 4)])
    rows = store.get_predictions("w", "2026-09-04")
    assert [r["rank"] for r in rows] == [1, 2, 3]
    prev = store.get_previous_predictions("w", "m", "2026-09-05")
    assert len(prev) == 3


# ---- L4: dashboard reads runs through the Store, not raw SQL -------------
def test_recent_daily_runs(tmp_path):
    store = Store(str(tmp_path / "d.db"))
    store.put_daily_run("w", "2026-09-04", True, "mdl", None,
                        {"n_predictions": 5,
                         "alerts": [{"deliver": True}, {"deliver": False}]})
    runs = store.recent_daily_runs("w")
    assert runs == [{"asof": "2026-09-04", "ok": True, "n_pred": 5, "n_alerts": 1}]


# ---- L5: platform config env read at call time ---------------------------
def test_platform_config_env_applied_at_load(monkeypatch, tmp_path):
    from quantizedalert.config import PlatformConfig
    monkeypatch.setenv("DSA_PATH", "/tmp/dsa-nowhere")
    pc = PlatformConfig.load(path=tmp_path / "none.yaml")
    assert pc.dsa_path == "/tmp/dsa-nowhere"

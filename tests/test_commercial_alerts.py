"""Offline regressions for pure decision logic (no qlib/DSA execution).

Covers the two places a silent bug destroys revenue or trust:
plan quota enforcement + contribution math, and alert prioritization/suppression.
"""
from __future__ import annotations

import pytest

from quantizedalert.alerts.intelligence import AlertIntelligence
from quantizedalert.commercial.plans import PLANS, Metering, QuotaError, contribution_margin
from quantizedalert.config import AlertPrefs
from quantizedalert.schemas import AlertEvent, Severity, new_id
from quantizedalert.store import Store


@pytest.fixture()
def store(tmp_path):
    return Store(str(tmp_path / "t.db"))


class FakeAlerter:
    engine_source = "fake"

    def __init__(self):
        self.sent = []

    def dispatch(self, md, channels, severity=None, dedup_key=None,
                 cooldown_key=None, route_type=None):
        self.sent.append(md)
        return dict.fromkeys(channels, True)


def _ev(kind="signal_change", sev=Severity.HIGH, insts=("SH600000",),
        comps=None) -> AlertEvent:
    return AlertEvent(new_id("evt"), "w1", kind, f"t-{kind}", "body", sev,
                      instruments=list(insts),
                      components=comps or {"confidence": 0.7})


# ---------- quotas / economics ----------
def test_free_research_quota_enforced(store):
    m = Metering(store)
    for _ in range(PLANS["free"]["research_jobs_month"]):
        m.research("w1", "free")
    with pytest.raises(QuotaError):
        m.research("w1", "free")


def test_alert_budget_per_day(store):
    m = Metering(store)
    cap = PLANS["free"]["alerts_day"]
    for _ in range(cap):
        m.alert("w1", "free")
    with pytest.raises(QuotaError):
        m.alert("w1", "free")


def test_contribution_margin_uses_real_metered_usage(store):
    m = Metering(store)
    m.inference("w1", "individual")
    c = contribution_margin(store, "w1", "individual")
    assert c["contribution"] == pytest.approx(
        PLANS["individual"]["price_month_usd"] - c["total_cost"])
    assert c["usage"]["inference_jobs"] >= 1


# ---------- alert intelligence ----------
def test_low_severity_suppressed_by_min_severity(store):
    # components pushed high so min_score can't be the blocker; severity is
    prefs = AlertPrefs(min_severity="medium", min_score=0.4,
                       channels=["custom_webhook"])
    al = FakeAlerter()
    ai = AlertIntelligence(store, al, prefs)
    d = ai.process([_ev(sev=Severity.LOW, insts=("SH600000",),
                        comps={"confidence": 1.0, "risk": 1.0,
                               "historical_significance": 1.0})],
                   "w1", "2026-09-04", {"SH600000"})
    assert len(d) == 1 and not d[0].deliver
    assert "min_severity" in (d[0].suppress_reason or "")


def test_daily_budget_and_priority(store):
    prefs = AlertPrefs(max_alerts_per_day=2, min_severity="low",
                       channels=["custom_webhook"])
    al = FakeAlerter()
    ai = AlertIntelligence(store, al, prefs)
    evs = [_ev(sev=Severity.CRITICAL, insts=("A",),
               comps={"confidence": 0.9}),
           _ev(sev=Severity.HIGH, insts=("B",)),
           _ev(sev=Severity.LOW, insts=("C",), comps={"confidence": 0.2})]
    d = ai.process(evs, "w1", "2026-09-04", set())
    assert d[0].event.instruments[0] == "A"  # priority order by value
    delivered = [x for x in d if x.deliver]
    assert len(delivered) == 2
    assert {x.event.instruments[0] for x in delivered} == {"A", "B"}
    assert len(al.sent) == 2


def test_dedup_window_blocks_repeat(store):
    prefs = AlertPrefs(max_alerts_per_day=10, min_severity="low",
                       dedup_window_hours=24, channels=["custom_webhook"])
    al = FakeAlerter()
    ai = AlertIntelligence(store, al, prefs)
    e1 = _ev(insts=("SH600000",))
    e1.dedup_key = "w1:signal_change:SH600000"
    ai.process([e1], "w1", "2026-09-04", set())
    e2 = _ev(insts=("SH600000",))
    e2.dedup_key = e1.dedup_key
    d = ai.process([e2], "w1", "2026-09-04", set())
    assert not d[0].deliver
    assert "dedup" in (d[0].suppress_reason or "")

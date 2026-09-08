"""Layer G — Alert Intelligence.

Objective §7: "fewer, higher-value alerts." Every candidate event is scored on
severity, novelty, confidence, portfolio relevance, risk, historical
significance, and user preferences; then gated by score threshold, per-day
budget, quiet hours, dedup/cooldown, and min severity. Suppressed events are
still recorded (audit + engagement analytics).

Delivery itself is delegated to the DSA asset (dsa_dispatch.DSAlerter).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from unlockaid.schemas import AlertDecision, AlertEvent, Severity
from unlockaid.store import Store, utcnow

logger = logging.getLogger("unlockaid.alerts")

# weights for value score (sum to 1.0)
WEIGHTS = {
    "severity": 0.30,
    "novelty": 0.15,
    "confidence": 0.15,
    "portfolio_relevance": 0.25,
    "risk": 0.10,
    "history": 0.05,
}


def _parse_hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def in_quiet_hours(now_local_minutes: int, start: str, end: str) -> bool:
    """Quiet window may wrap midnight (23:00-07:00)."""
    a, b = _parse_hhmm(start), _parse_hhmm(end)
    if a <= b:
        return a <= now_local_minutes < b
    return now_local_minutes >= a or now_local_minutes < b


class AlertIntelligence:
    """Scores, gates, and dispatches alert events for one workspace."""

    def __init__(self, store: Store, alerter, prefs,
                 tz_offset_hours: int = 8):  # Asia/Shanghai default
        self.store = store
        self.alerter = alerter
        self.prefs = prefs
        self.tz_offset = tz_offset_hours

    # ---------- scoring ----------
    def score(self, e: AlertEvent, held_instruments: set[str],
              recent_delivered: list[dict]) -> dict[str, float]:
        sev = e.severity.rank / 5.0
        sim_kind = [a for a in recent_delivered
                    if a["kind"] == e.kind and a["deliver"]]
        novelty = 1.0
        if sim_kind:
            ages_h = [(datetime.now(timezone.utc)
                       - datetime.strptime(a["created_at"], "%Y-%m-%dT%H:%M:%SZ")
                       .replace(tzinfo=timezone.utc)
                       ).total_seconds() / 3600 for a in sim_kind]
            novelty = max(0.0, min(1.0, min(ages_h) / 24.0))
        conf = min(1.0, max(0.0, e.components.get("confidence", 0.5)))
        port_rel = 1.0 if (set(e.instruments) & held_instruments) else 0.25
        risk = min(1.0, max(0.0, e.components.get("risk", sev)))
        hist = min(1.0, max(0.0, e.components.get("historical_significance", sev)))
        return {"severity": sev, "novelty": novelty, "confidence": conf,
                "portfolio_relevance": port_rel, "risk": risk, "history": hist}

    def value(self, components: dict[str, float]) -> float:
        return sum(WEIGHTS[k] * components[k] for k in WEIGHTS)

    # ---------- gating + dispatch ----------
    def process(self, events: list[AlertEvent], workspace_id: str, asof: str,
                held_instruments: set[str],
                quiet_now_minutes: Optional[int] = None) -> list[AlertDecision]:
        """Rank, gate, deliver. Returns decisions in priority order (all recorded)."""
        decisions: list[AlertDecision] = []
        recent = self.store.recent_alerts(workspace_id, since_hours=72)
        budget_used = sum(1 for a in recent if a["deliver"] and a["asof"] == asof)
        min_rank = Severity(self.prefs.min_severity).rank

        for e in events:
            e.components = self.score(e, held_instruments, recent)
            e.score = self.value(e.components)
            e.created_at = e.created_at or utcnow()
            # instrument-specific fallback: distinct signal changes for distinct
            # names are distinct events; kind-only keys would collapse them.
            e.dedup_key = e.dedup_key or (
                f"{workspace_id}:{e.kind}:"
                + ":".join(sorted(e.instruments)[:3]))
        ranked = sorted(events, key=lambda x: -x.score)

        if quiet_now_minutes is not None:
            local_min = quiet_now_minutes
        else:
            now = datetime.now(timezone.utc)
            local_min = (now.hour * 60 + now.minute + self.tz_offset * 60) % 1440
        quiet = (in_quiet_hours(local_min, self.prefs.quiet_hours[0],
                                self.prefs.quiet_hours[1])
                 if self.prefs.quiet_hours else False)

        for e in ranked:
            reason: Optional[str] = None
            if e.score < self.prefs.min_score:
                reason = f"score {e.score:.2f} < min_score {self.prefs.min_score}"
            elif e.severity.rank < min_rank:
                reason = f"below min_severity {self.prefs.min_severity}"
            elif budget_used >= self.prefs.max_alerts_per_day:
                reason = "daily alert budget exhausted"
            elif quiet and e.severity.rank < Severity.HIGH.rank:
                reason = "quiet hours"          # critical/high break through
            elif self.store.alert_dedup_exists(workspace_id, e.dedup_key,
                                               self.prefs.dedup_window_hours):
                reason = "dedup window"

            deliver = reason is None
            channels: list[str] = []
            delivered: dict[str, bool] = {}
            if deliver:
                channels = list(self.prefs.channels)
                delivered = self.alerter.dispatch(
                    self._render(e), channels,
                    severity=e.severity.value, dedup_key=e.dedup_key)
                budget_used += 1
                if not any(delivered.values()):
                    deliver = False
                    reason = "delivery failed on all channels"

            self.store.record_alert({
                "event_id": e.event_id, "workspace_id": workspace_id,
                "kind": e.kind, "title": e.title,
                "severity": e.severity.value, "score": e.score,
                "components": e.components, "instruments": e.instruments,
                "models": e.models, "deliver": deliver,
                "suppress_reason": reason, "channels": channels,
                "delivered": delivered, "asof": asof, "dedup_key": e.dedup_key,
                "created_at": e.created_at})
            decisions.append(AlertDecision(
                event=e, deliver=deliver, suppress_reason=reason,
                channels=channels, delivered=delivered,
                engine_source=f"unlockaid+{self.alerter.engine_source}"))
        return decisions

    @staticmethod
    def _render(e: AlertEvent) -> str:
        return (f"### [{e.severity.value.upper()}] {e.title}\n\n"
                f"{e.body_md}\n\n_{e.kind} · UnlockAid_\n")

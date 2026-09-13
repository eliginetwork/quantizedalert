"""Shadow Regret Engine — Closed-loop learning from trading signals and outcomes.

Calculates regret metrics:
1. False Positive Regret (Type I): Alert fired but stock lost money or lagged benchmark.
2. False Negative Regret (Type II): Candidate was suppressed but stock rallied significantly.
3. Adaptive parameter tuning: Dynamically adjusts conviction and alert score thresholds
   to minimize total regret.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("quantizedalert.learning.regret")


class RegretType(str, Enum):
    TRUE_POSITIVE = "TRUE_POSITIVE"      # Fired & Won
    FALSE_POSITIVE = "FALSE_POSITIVE"    # Fired & Lost (Type I Error)
    FALSE_NEGATIVE = "FALSE_NEGATIVE"    # Suppressed & Surged (Type II Error)
    TRUE_NEGATIVE = "TRUE_NEGATIVE"      # Suppressed & Dropped / Flat (Correct Gating)


@dataclass
class OutcomeRecord:
    signal_id: str
    ticker: str
    asof: str
    delivered: bool
    conviction_score: float
    entry_price: float
    exit_price: float | None = None
    return_pct: float | None = None
    benchmark_return_pct: float | None = None
    excess_return_pct: float | None = None
    regret_type: RegretType = RegretType.TRUE_POSITIVE
    regret_penalty: float = 0.0
    sector: str = ""
    evaluated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["regret_type"] = self.regret_type.value
        return d


@dataclass
class RegretReport:
    total_signals: int
    evaluated_signals: int
    win_rate: float
    false_positive_rate: float
    false_negative_rate: float
    total_regret_penalty: float
    recommended_conviction_adjustment: float
    sector_performance: dict[str, dict[str, float]] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ShadowRegretEngine:
    """Tracks signals and outcomes to auto-tune filtering thresholds."""

    def __init__(self, state_dir: Path | str = "market_cache/learning"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.signals_file = self.state_dir / "recorded_signals.json"
        self.outcomes_file = self.state_dir / "evaluated_outcomes.json"
        self.signals: list[dict[str, Any]] = []
        self.outcomes: list[OutcomeRecord] = []
        self._load_state()

    def _load_state(self) -> None:
        if self.signals_file.exists():
            try:
                self.signals = json.loads(self.signals_file.read_text())
            except Exception as e:
                logger.debug("Failed loading recorded signals: %s", e)

        if self.outcomes_file.exists():
            try:
                data = json.loads(self.outcomes_file.read_text())
                self.outcomes = [
                    OutcomeRecord(
                        signal_id=o["signal_id"],
                        ticker=o["ticker"],
                        asof=o["asof"],
                        delivered=o["delivered"],
                        conviction_score=o["conviction_score"],
                        entry_price=o["entry_price"],
                        exit_price=o.get("exit_price"),
                        return_pct=o.get("return_pct"),
                        benchmark_return_pct=o.get("benchmark_return_pct"),
                        excess_return_pct=o.get("excess_return_pct"),
                        regret_type=RegretType(o["regret_type"]),
                        regret_penalty=o.get("regret_penalty", 0.0),
                        sector=o.get("sector", ""),
                        evaluated_at=o.get("evaluated_at", ""),
                    )
                    for o in data
                ]
            except Exception as e:
                logger.debug("Failed loading evaluated outcomes: %s", e)

    def _save_state(self) -> None:
        try:
            self.signals_file.write_text(json.dumps(self.signals[-500:], indent=2))
            self.outcomes_file.write_text(json.dumps([o.to_dict() for o in self.outcomes[-500:]], indent=2))
        except Exception as e:
            logger.warning("Failed saving learning state: %s", e)

    def record_signal(self, signal_id: str, ticker: str, asof: str,
                      conviction_score: float, delivered: bool,
                      entry_price: float, sector: str = "") -> None:
        """Record a generated signal for future regret evaluation."""
        self.signals.append({
            "signal_id": signal_id,
            "ticker": ticker.upper().strip(),
            "asof": asof,
            "conviction_score": round(conviction_score, 1),
            "delivered": delivered,
            "entry_price": round(entry_price, 2),
            "sector": sector,
            "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        self._save_state()

    def evaluate_outcomes(self, current_prices: dict[str, float] | Callable[[str], float | None],
                          benchmark_return_pct: float = 0.0) -> RegretReport:
        """Evaluate recorded signals against current prices to compute regret."""
        evaluated: list[OutcomeRecord] = []
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")

        sector_stats: dict[str, list[float]] = {}

        for sig in self.signals:
            ticker = sig["ticker"]
            entry = sig["entry_price"]
            if entry <= 0.0:
                continue

            # Price lookup
            if callable(current_prices):
                curr_price = current_prices(ticker)
            else:
                curr_price = current_prices.get(ticker)

            if curr_price is None or curr_price <= 0.0:
                continue

            ret_pct = ((curr_price - entry) / entry) * 100.0
            excess_ret = ret_pct - benchmark_return_pct
            delivered = sig["delivered"]
            conv = sig["conviction_score"]
            sec = sig.get("sector", "general")

            if sec not in sector_stats:
                sector_stats[sec] = []
            sector_stats[sec].append(ret_pct)

            # Categorize Regret
            if delivered:
                if excess_ret >= 0.0:
                    rtype = RegretType.TRUE_POSITIVE
                    penalty = 0.0
                else:
                    rtype = RegretType.FALSE_POSITIVE
                    # Penalty proportional to underperformance
                    penalty = abs(excess_ret)
            else:
                # Suppressed candidate
                if ret_pct >= 3.0:  # Rallied 3%+ despite being suppressed
                    rtype = RegretType.FALSE_NEGATIVE
                    penalty = ret_pct
                else:
                    rtype = RegretType.TRUE_NEGATIVE
                    penalty = 0.0

            out = OutcomeRecord(
                signal_id=sig["signal_id"],
                ticker=ticker,
                asof=sig["asof"],
                delivered=delivered,
                conviction_score=conv,
                entry_price=entry,
                exit_price=round(curr_price, 2),
                return_pct=round(ret_pct, 2),
                benchmark_return_pct=round(benchmark_return_pct, 2),
                excess_return_pct=round(excess_ret, 2),
                regret_type=rtype,
                regret_penalty=round(penalty, 2),
                sector=sec,
                evaluated_at=now_str,
            )
            evaluated.append(out)

        self.outcomes = evaluated
        self._save_state()

        # Generate summary report
        n = len(evaluated)
        if n == 0:
            return RegretReport(
                total_signals=len(self.signals),
                evaluated_signals=0,
                win_rate=0.0,
                false_positive_rate=0.0,
                false_negative_rate=0.0,
                total_regret_penalty=0.0,
                recommended_conviction_adjustment=0.0,
                summary="No signals could be evaluated (missing current price data).",
            )

        delivered_outcomes = [o for o in evaluated if o.delivered]
        n_del = len(delivered_outcomes)
        wins = sum(1 for o in delivered_outcomes if o.regret_type == RegretType.TRUE_POSITIVE)
        win_rate = (wins / n_del * 100.0) if n_del > 0 else 0.0

        fps = sum(1 for o in delivered_outcomes if o.regret_type == RegretType.FALSE_POSITIVE)
        fp_rate = (fps / n_del * 100.0) if n_del > 0 else 0.0

        suppressed = [o for o in evaluated if not o.delivered]
        n_sup = len(suppressed)
        fns = sum(1 for o in suppressed if o.regret_type == RegretType.FALSE_NEGATIVE)
        fn_rate = (fns / n_sup * 100.0) if n_sup > 0 else 0.0

        total_penalty = sum(o.regret_penalty for o in evaluated)

        # Adaptive threshold adjustment calculation
        # If FP rate is high (>35%), tighten gating (+1.5 to +4.0 pts)
        # If FN rate is high (>25%), loosen gating (-1.5 to -3.0 pts)
        adj = 0.0
        if fp_rate > 35.0:
            adj = min(5.0, (fp_rate - 35.0) * 0.15)
        elif fn_rate > 25.0:
            adj = -min(5.0, (fn_rate - 25.0) * 0.15)

        sec_summary = {}
        for s, rets in sector_stats.items():
            if rets:
                sec_summary[s] = {
                    "avg_return": round(float(sum(rets) / len(rets)), 2),
                    "count": len(rets),
                }

        summary_text = (
            f"Evaluated {n} signals: {win_rate:.1f}% Win Rate on delivered alerts. "
            f"FP Rate: {fp_rate:.1f}%, FN Rate: {fn_rate:.1f}%. "
            f"Recommended Conviction Adjustment: {adj:+.1f} pts."
        )

        return RegretReport(
            total_signals=len(self.signals),
            evaluated_signals=n,
            win_rate=round(win_rate, 1),
            false_positive_rate=round(fp_rate, 1),
            false_negative_rate=round(fn_rate, 1),
            total_regret_penalty=round(total_penalty, 2),
            recommended_conviction_adjustment=round(adj, 1),
            sector_performance=sec_summary,
            summary=summary_text,
        )


"""Multi-Factor Conviction Gating Engine.

Combines 4 independent signal pillars to eliminate false positives:
1. Quantitative Model Score (Qlib LightGBM factor rank / trend): 40%
2. Fundamental Health (SEC EDGAR metrics / balance sheet soundness): 30%
3. Insider Ownership & Screener Discovery (SWS screeners / Form 4 buys): 20%
4. Sector Momentum Alignment (relative strength vs SPY): 10%

Only setups achieving >= 65.0 conviction score pass gating for active delivery.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from quantizedalert.discovery.fundamentals import FundamentalAnalyzer, FundamentalRating

logger = logging.getLogger("quantizedalert.discovery.conviction")


@dataclass
class ConvictionScore:
    """Composite conviction output for a candidate instrument."""

    ticker: str
    composite_conviction: float    # 0-100
    passes_gate: bool              # >= threshold
    quant_score: float             # 0-100
    fundamental_score: float       # 0-100
    insider_score: float           # 0-100
    sector_score: float            # 0-100
    fundamental_rating: str        # STRONG, MODERATE, WEAK
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConvictionEngine:
    """Calculates multi-factor conviction and applies gate filtering."""

    def __init__(self, threshold: float = 65.0,
                 quant_weight: float = 0.40,
                 fund_weight: float = 0.30,
                 insider_weight: float = 0.20,
                 sector_weight: float = 0.10):
        self.threshold = threshold
        self.quant_weight = quant_weight
        self.fund_weight = fund_weight
        self.insider_weight = insider_weight
        self.sector_weight = sector_weight
        self.fund_analyzer = FundamentalAnalyzer()

    def evaluate(self, ticker: str,
                 quant_score_raw: float,
                 fundamentals: dict[str, Any] | None = None,
                 sws_candidates: list[dict[str, Any]] | None = None,
                 sector_rating: float | None = None) -> ConvictionScore:
        """Evaluate a single ticker across all 4 pillars."""
        t_clean = ticker.upper().strip()

        # 1. Normalize quant score to 0-100
        # If quant_score_raw is 0-1 probability/score: multiply by 100
        q_score = (
            quant_score_raw * 100.0
            if quant_score_raw <= 1.5 and quant_score_raw >= 0.0
            else float(np.clip(quant_score_raw, 0.0, 100.0))
        )

        # 2. Fundamental & Insider analysis
        fund_res = self.fund_analyzer.analyze(t_clean, fundamentals=fundamentals,
                                              sws_candidates=sws_candidates)
        f_score = fund_res.fundamental_score
        i_score = fund_res.insider_score

        # 3. Sector rating (default 50 if unspecified)
        s_score = float(sector_rating if sector_rating is not None else 50.0)

        # 4. Composite calculation
        composite = (
            self.quant_weight * q_score +
            self.fund_weight * f_score +
            self.insider_weight * i_score +
            self.sector_weight * s_score
        )
        composite = round(float(np.clip(composite, 0.0, 100.0)), 1)
        passes = composite >= self.threshold

        reasons = []
        if q_score >= 70:
            reasons.append(f"Strong quant score ({q_score:.1f})")
        if fund_res.rating == FundamentalRating.STRONG:
            reasons.append(f"Strong fundamentals ({f_score:.1f})")
        elif fund_res.rating == FundamentalRating.WEAK:
            reasons.append(f"Weak balance sheet/margins ({f_score:.1f})")
        if i_score >= 75:
            reasons.append("High insider conviction/discovery match")
        if s_score >= 65:
            reasons.append(f"Leading sector momentum ({s_score:.1f})")
        elif s_score <= 40:
            reasons.append(f"Lagging sector drag ({s_score:.1f})")

        return ConvictionScore(
            ticker=t_clean,
            composite_conviction=composite,
            passes_gate=passes,
            quant_score=round(q_score, 1),
            fundamental_score=round(f_score, 1),
            insider_score=round(i_score, 1),
            sector_score=round(s_score, 1),
            fundamental_rating=fund_res.rating.value,
            reasons=reasons,
        )

    def filter_gated_alerts(self, candidates: list[dict[str, Any]],
                            min_threshold: float | None = None) -> list[ConvictionScore]:
        """Filter a list of candidate items, returning only those passing the threshold."""
        thresh = min_threshold if min_threshold is not None else self.threshold
        results = []
        for c in candidates:
            score = self.evaluate(
                ticker=c.get("ticker") or c.get("instrument", ""),
                quant_score_raw=float(c.get("score") or 0.5),
                fundamentals=c.get("fundamentals"),
                sws_candidates=c.get("sws_candidates"),
                sector_rating=c.get("sector_rating"),
            )
            if score.composite_conviction >= thresh:
                results.append(score)
        return sorted(results, key=lambda s: s.composite_conviction, reverse=True)


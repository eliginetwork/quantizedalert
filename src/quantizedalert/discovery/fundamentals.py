"""Fundamental and Insider Analysis Engine.

Performs multi-metric health evaluations (SEC EDGAR metrics and yfinance ratios):
1. Revenue Growth, Net Margin, Debt-to-Equity, Current Ratio, ROE.
2. Fundamental Health Score (0-100) and Categorical Rating (STRONG, MODERATE, WEAK).
3. Insider Purchasing & Form 4 Analysis: Conviction scoring based on executive cluster buys.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger("quantizedalert.discovery.fundamentals")


class FundamentalRating(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    UNKNOWN = "N/A"


@dataclass
class FundamentalAnalysisResult:
    ticker: str
    rating: FundamentalRating
    fundamental_score: float   # 0-100
    insider_score: float       # 0-100
    revenue_growth: float | None = None
    net_margin: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    roe: float | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "rating": self.rating.value,
            "fundamental_score": self.fundamental_score,
            "insider_score": self.insider_score,
            "revenue_growth": self.revenue_growth,
            "net_margin": self.net_margin,
            "debt_to_equity": self.debt_to_equity,
            "current_ratio": self.current_ratio,
            "roe": self.roe,
            "notes": self.notes,
        }


class FundamentalAnalyzer:
    """Evaluates company balance sheet strength, growth rate, and insider ownership."""

    def rate_fundamentals(self, metrics: dict[str, Any]) -> tuple[FundamentalRating, float]:
        """Score fundamental health based on standard SEC / financial metrics.

        Returns (FundamentalRating, score_0_to_100).
        """
        score = 0.0
        max_score = 0.0

        # Revenue growth (>20% = strong, >10% = moderate, >0% = positive)
        rg = metrics.get("revenue_growth")
        if rg is not None:
            max_score += 2.0
            if rg > 0.20:
                score += 2.0
            elif rg > 0.10:
                score += 1.5
            elif rg > 0.0:
                score += 1.0

        # Net margin (>15% = strong, >5% = ok)
        nm = metrics.get("net_margin")
        if nm is not None:
            max_score += 2.0
            if nm > 0.20:
                score += 2.0
            elif nm > 0.10:
                score += 1.5
            elif nm > 0.03:
                score += 1.0

        # Debt-to-Equity (<0.5 = strong, <1.0 = moderate, <2.0 = acceptable)
        de = metrics.get("debt_to_equity")
        if de is not None:
            max_score += 2.0
            if de < 0.4:
                score += 2.0
            elif de < 0.8:
                score += 1.5
            elif de < 1.5:
                score += 1.0
            elif de < 2.5:
                score += 0.5

        # Current ratio (>2.0 = safe, >1.3 = adequate)
        cr = metrics.get("current_ratio")
        if cr is not None:
            max_score += 2.0
            if cr > 2.0:
                score += 2.0
            elif cr > 1.3:
                score += 1.5
            elif cr > 1.0:
                score += 1.0

        # Return on Equity (>20% = strong, >12% = good)
        roe = metrics.get("roe")
        if roe is not None:
            max_score += 2.0
            if roe > 0.20:
                score += 2.0
            elif roe > 0.12:
                score += 1.5
            elif roe > 0.05:
                score += 1.0

        if max_score == 0.0:
            return FundamentalRating.UNKNOWN, 50.0

        pct = (score / max_score) * 100.0
        if pct >= 70.0:
            rating = FundamentalRating.STRONG
        elif pct >= 45.0:
            rating = FundamentalRating.MODERATE
        else:
            rating = FundamentalRating.WEAK

        return rating, round(pct, 1)

    def evaluate_insider_activity(self, ticker: str,
                                   sws_candidates: list[dict[str, Any]] | None = None) -> float:
        """Score insider purchasing intensity (0-100)."""
        t_clean = ticker.upper().strip()
        if not sws_candidates:
            return 40.0  # neutral baseline

        # Check if the stock is featured in insider screeners
        insider_score = 40.0
        for cand in sws_candidates:
            if cand.get("ticker", "").upper() == t_clean:
                cat = cand.get("category", "").lower()
                if "insider" in cat:
                    insider_score = max(insider_score, 85.0)
                # Snowflake health bonus
                if cand.get("score_health", 0) >= 5:
                    insider_score = min(100.0, insider_score + 10.0)

        return insider_score

    def analyze(self, ticker: str, fundamentals: dict[str, Any] | None = None,
                sws_candidates: list[dict[str, Any]] | None = None) -> FundamentalAnalysisResult:
        """Perform comprehensive fundamental and insider evaluation for a ticker."""
        funds = fundamentals or {}
        rating, fund_score = self.rate_fundamentals(funds)
        insider_score = self.evaluate_insider_activity(ticker, sws_candidates)

        return FundamentalAnalysisResult(
            ticker=ticker.upper().strip(),
            rating=rating,
            fundamental_score=fund_score,
            insider_score=insider_score,
            revenue_growth=funds.get("revenue_growth"),
            net_margin=funds.get("net_margin"),
            debt_to_equity=funds.get("debt_to_equity"),
            current_ratio=funds.get("current_ratio"),
            roe=funds.get("roe"),
            notes=f"Rating: {rating.value} (FundScore: {fund_score}, Insider: {insider_score})",
        )


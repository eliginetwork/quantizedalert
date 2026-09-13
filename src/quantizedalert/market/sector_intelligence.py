"""Sector Intelligence — Per-sector momentum, valuation, and fundamental analysis for US Equities.

Evaluates the 11 S&P 500 GICS sectors:
1. Momentum tracking: 1M, 3M, 6M returns relative to SPY.
2. Technical health: SMA-50, SMA-200 alignment and RSI-14.
3. Composite sector rating (0-100) and market direction bias (LONG, SHORT, NEUTRAL).
4. Identification of leading sector stocks for watchlist expansion.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quantizedalert.market.yfinance_client import (
    get_historical_prices,
)

logger = logging.getLogger("quantizedalert.market.sector_intel")

# 11 S&P 500 GICS Sectors & Representative ETFs
SECTOR_ETFS: dict[str, str] = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
    "XLU": "Utilities",
}

# Top representative holdings per sector
SECTOR_STOCKS: dict[str, list[str]] = {
    "XLK": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "AMD", "ADBE", "QCOM", "NOW"],
    "XLF": ["JPM", "V", "MA", "GS", "BLK", "AXP", "MS", "SCHW", "C", "BAC"],
    "XLV": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "ABT", "PFE", "AMGN", "ISRG"],
    "XLY": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "BKNG", "TJX", "CMG"],
    "XLP": ["WMT", "PG", "COST", "KO", "PEP", "CL", "MDLZ", "KMB", "SYY", "GIS"],
    "XLE": ["XOM", "CVX", "COP", "EOG", "SLB", "OXY", "MPC", "PSX", "VLO", "HAL"],
    "XLI": ["CAT", "GE", "BA", "HON", "RTX", "UPS", "LMT", "DE", "MMM", "ETN"],
    "XLB": ["LIN", "SHW", "FCX", "APD", "NEM", "ECL", "DOW", "DD", "PPG", "CTVA"],
    "XLRE": ["PLD", "AMT", "EQIX", "CCI", "SPG", "PSA", "WELL", "O", "DLR", "AVB"],
    "XLC": ["META", "GOOGL", "NFLX", "DIS", "CMCSA", "VZ", "T", "CHTR", "EA", "TTWO"],
    "XLU": ["NEE", "DUK", "SO", "AEP", "SRE", "D", "EXC", "PEG", "ED", "AWK"],
}


@dataclass
class SectorRating:
    """Rating and diagnostic state for a specific US sector."""

    sector_etf: str
    sector_name: str
    rating: float               # 0-100 composite
    direction: str              # LONG, SHORT, NEUTRAL
    confidence: float           # 0-100

    # Momentum metrics
    momentum_1m: float = 0.0
    momentum_3m: float = 0.0
    momentum_6m: float = 0.0
    relative_strength_1m: float = 0.0   # vs SPY
    momentum_score: float = 50.0

    # Technical health
    above_sma_50: bool = False
    above_sma_200: bool = False
    rsi_14: float = 50.0

    # Top holdings and picks
    top_picks: list[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SectorIntelligence:
    """Analyzes US sectors and scores market momentum and risk alignment."""

    def __init__(self, cache_dir: Path | str = "market_cache/sector_intel",
                 cache_ttl: float = 3600.0):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "sector_ratings.json"
        self.cache_ttl = cache_ttl

    def _load_cache(self) -> dict[str, SectorRating] | None:
        if not self.cache_file.exists():
            return None
        try:
            age = time.time() - self.cache_file.stat().st_mtime
            if age < self.cache_ttl:
                data = json.loads(self.cache_file.read_text())
                ratings = {}
                for k, v in data.items():
                    ratings[k] = SectorRating(**v)
                return ratings
        except Exception as e:
            logger.debug("Failed reading sector ratings cache: %s", e)
        return None

    def _save_cache(self, ratings: dict[str, SectorRating]) -> None:
        try:
            payload = {k: r.to_dict() for k, r in ratings.items()}
            self.cache_file.write_text(json.dumps(payload, indent=2))
        except Exception as e:
            logger.warning("Failed saving sector ratings cache: %s", e)

    def _calc_rsi(self, series: pd.Series, period: int = 14) -> float:
        """Calculate 14-period RSI."""
        if len(series) < period + 1:
            return 50.0
        delta = series.diff().dropna()
        gain = (delta.where(delta > 0, 0.0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        val = rsi.iloc[-1]
        return float(val) if np.isfinite(val) else 50.0

    def rate_sector(self, sector_etf: str, spy_df: pd.DataFrame | None = None) -> SectorRating:
        """Calculate quantitative rating for a given sector ETF."""
        etf_clean = sector_etf.upper().strip()
        sector_name = SECTOR_ETFS.get(etf_clean, "Unknown Sector")

        # Fetch ETF historical bars (1 year)
        etf_df = get_historical_prices(etf_clean, period="1y")
        if etf_df is None or etf_df.empty or len(etf_df) < 20:
            return SectorRating(
                sector_etf=etf_clean,
                sector_name=sector_name,
                rating=50.0,
                direction="NEUTRAL",
                confidence=20.0,
                top_picks=SECTOR_STOCKS.get(etf_clean, [])[:3],
                timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            )

        close = etf_df["Close"]
        curr_price = float(close.iloc[-1])

        # Benchmark SPY data for relative strength
        if spy_df is None:
            spy_df = get_historical_prices("SPY", period="1y")

        # Momentum calculations
        n = len(close)
        ret_1m = float(curr_price / close.iloc[-min(21, n)] - 1.0) if n >= 21 else 0.0
        ret_3m = float(curr_price / close.iloc[-min(63, n)] - 1.0) if n >= 63 else 0.0
        ret_6m = float(curr_price / close.iloc[-min(126, n)] - 1.0) if n >= 126 else 0.0

        # SPY 1m return
        spy_1m = 0.0
        if spy_df is not None and not spy_df.empty and len(spy_df) >= 21:
            spy_close = spy_df["Close"]
            spy_1m = float(spy_close.iloc[-1] / spy_close.iloc[-min(21, len(spy_close))] - 1.0)

        rel_strength_1m = ret_1m - spy_1m

        # Moving averages
        sma_50 = float(close.rolling(50).mean().iloc[-1]) if n >= 50 else curr_price
        sma_200 = float(close.rolling(200).mean().iloc[-1]) if n >= 200 else curr_price
        above_sma_50 = bool(curr_price > sma_50)
        above_sma_200 = bool(curr_price > sma_200)

        # Technical indicators
        rsi_val = self._calc_rsi(close, period=14)

        # Composite score calculation (0-100)
        # Baseline = 50
        score = 50.0
        score += rel_strength_1m * 100.0 * 1.5   # +15 pts per 10% outperformance
        score += ret_3m * 50.0                  # +5 pts per 10% 3M gain
        if above_sma_50:
            score += 10.0
        if above_sma_200:
            score += 10.0
        if rsi_val > 50:
            score += (rsi_val - 50.0) * 0.4
        else:
            score -= (50.0 - rsi_val) * 0.4

        rating = float(np.clip(score, 5.0, 95.0))

        # Direction bias
        if rating >= 65.0:
            direction = "LONG"
        elif rating <= 38.0:
            direction = "SHORT"
        else:
            direction = "NEUTRAL"

        confidence = float(np.clip(abs(rating - 50.0) * 2.0, 10.0, 95.0))

        return SectorRating(
            sector_etf=etf_clean,
            sector_name=sector_name,
            rating=round(rating, 2),
            direction=direction,
            confidence=round(confidence, 1),
            momentum_1m=round(ret_1m, 4),
            momentum_3m=round(ret_3m, 4),
            momentum_6m=round(ret_6m, 4),
            relative_strength_1m=round(rel_strength_1m, 4),
            momentum_score=round(float(np.clip(50.0 + rel_strength_1m * 100.0, 0, 100)), 1),
            above_sma_50=above_sma_50,
            above_sma_200=above_sma_200,
            rsi_14=round(rsi_val, 1),
            top_picks=SECTOR_STOCKS.get(etf_clean, [])[:3],
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
        )

    def rate_all_sectors(self, force_refresh: bool = False) -> dict[str, SectorRating]:
        """Rate all 11 S&P 500 sectors, utilizing cached results when fresh."""
        if not force_refresh:
            cached = self._load_cache()
            if cached is not None:
                return cached

        spy_df = get_historical_prices("SPY", period="1y")
        ratings: dict[str, SectorRating] = {}
        for etf in SECTOR_ETFS:
            ratings[etf] = self.rate_sector(etf, spy_df=spy_df)

        self._save_cache(ratings)
        return ratings

    def get_leading_sectors(self, top_n: int = 3) -> list[SectorRating]:
        """Return the top N strongest sectors ranked by rating."""
        all_ratings = self.rate_all_sectors()
        ranked = sorted(all_ratings.values(), key=lambda r: r.rating, reverse=True)
        return ranked[:top_n]


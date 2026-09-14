"""YFinance Client — Rate-limited, cached data fetcher for US Equities.

Prevents hitting Yahoo Finance rate limits with:
1. Thread-safe rate limiting (max 1 call per 0.6 seconds).
2. Dual-tier in-memory TTL caching (60s for prices, 300s for historical bars).
3. Defensive exception handling and clean type conversions.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pandas as pd

logger = logging.getLogger("quantizedalert.market.yfinance")


class RateLimiter:
    """Thread-safe rate limiter ensuring minimum interval between API calls."""

    def __init__(self, min_interval: float = 0.6):
        self.min_interval = min_interval
        self._last_call = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            elapsed = time.time() - self._last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_call = time.time()


# Global rate limiter instance
_rate_limiter = RateLimiter(min_interval=0.6)

# Cache dictionaries: key -> (data, timestamp)
_price_cache: dict[str, tuple[float, float]] = {}
_hist_cache: dict[str, tuple[pd.DataFrame, float]] = {}
_info_cache: dict[str, tuple[dict[str, Any], float]] = {}

PRICE_CACHE_TTL = 60.0    # 1 minute
HIST_CACHE_TTL = 300.0    # 5 minutes
INFO_CACHE_TTL = 900.0    # 15 minutes


def _cache_get(key: str, cache: dict, ttl: float) -> Any | None:
    if key in cache:
        value, timestamp = cache[key]
        if time.time() - timestamp < ttl:
            return value
    return None


def _cache_set(key: str, value: Any, cache: dict) -> None:
    cache[key] = (value, time.time())


def clear_cache() -> None:
    """Clear in-memory caches (primarily for unit testing)."""
    _price_cache.clear()
    _hist_cache.clear()
    _info_cache.clear()


def get_current_price(ticker: str, session: Any = None) -> float | None:
    """Fetch current market price for a given US or China ticker."""
    t_clean = ticker.upper().strip()
    cached = _cache_get(t_clean, _price_cache, PRICE_CACHE_TTL)
    if cached is not None:
        return cached

    # 1. Fast path: check unified live feed (Alpaca / Finnhub / Sina)
    try:
        from quantizedalert.market.live_feed import get_live_feed
        lq = get_live_feed().get_quote(t_clean)
        if lq and lq.price and lq.price > 0:
            _cache_set(t_clean, lq.price, _price_cache)
            return lq.price
    except Exception as e:
        logger.debug("Live feed lookup error for %s: %s", t_clean, e)

    # 2. Slow fallback: yfinance
    _rate_limiter.wait()
    try:
        import yfinance as yf
        kwargs = {"session": session} if session else {}
        t = yf.Ticker(t_clean, **kwargs)
        hist = t.history(period="2d")
        if hist is not None and not hist.empty and "Close" in hist.columns:
            price = float(hist["Close"].iloc[-1])
            _cache_set(t_clean, price, _price_cache)
            return price
        return None
    except Exception as e:
        logger.warning("Error fetching current price for %s: %s", t_clean, e)
        return None


def get_historical_prices(ticker: str, period: str = "6mo",
                           interval: str = "1d",
                           session: Any = None) -> pd.DataFrame | None:
    """Fetch historical OHLCV DataFrame for a ticker."""
    t_clean = ticker.upper().strip()
    cache_key = f"{t_clean}:{period}:{interval}"
    cached = _cache_get(cache_key, _hist_cache, HIST_CACHE_TTL)
    if cached is not None:
        return cached.copy()

    _rate_limiter.wait()
    try:
        import yfinance as yf
        kwargs = {"session": session} if session else {}
        t = yf.Ticker(t_clean, **kwargs)
        hist = t.history(period=period, interval=interval)
        if hist is not None and not hist.empty:
            _cache_set(cache_key, hist, _hist_cache)
            return hist.copy()
        return None
    except Exception as e:
        logger.warning("Error fetching historical prices for %s (%s): %s", t_clean, period, e)
        return None


def get_stock_fundamentals(ticker: str, session: Any = None) -> dict[str, Any]:
    """Fetch valuation and fundamental ratios for a ticker."""
    t_clean = ticker.upper().strip()
    cached = _cache_get(t_clean, _info_cache, INFO_CACHE_TTL)
    if cached is not None:
        return cached.copy()

    _rate_limiter.wait()
    result: dict[str, Any] = {
        "ticker": t_clean,
        "price": get_current_price(t_clean, session=session),
        "pe_ratio": None,
        "pb_ratio": None,
        "ps_ratio": None,
        "revenue_growth": None,
        "net_margin": None,
        "debt_to_equity": None,
        "current_ratio": None,
        "roe": None,
        "market_cap": None,
        "sector": None,
        "industry": None,
        "name": t_clean,
    }
    try:
        import yfinance as yf
        kwargs = {"session": session} if session else {}
        info = yf.Ticker(t_clean, **kwargs).info or {}
        result.update({
            "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
            "pb_ratio": info.get("priceToBook"),
            "ps_ratio": info.get("priceToSalesTrailingMonths"),
            "revenue_growth": info.get("revenueGrowth"),
            "net_margin": info.get("profitMargins"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "roe": info.get("returnOnEquity"),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "name": info.get("shortName") or t_clean,
        })
        _cache_set(t_clean, result, _info_cache)
    except Exception as e:
        logger.warning("Error fetching fundamentals for %s: %s", t_clean, e)
        result["error"] = str(e)
    return result


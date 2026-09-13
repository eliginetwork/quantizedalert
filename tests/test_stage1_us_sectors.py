"""Tests for Stage 1: US Equities & Sector Intelligence Expansion."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from quantizedalert.config import WorkspaceConfig
from quantizedalert.market.sector_intelligence import (
    SECTOR_ETFS,
    SECTOR_STOCKS,
    SectorIntelligence,
    SectorRating,
)
from quantizedalert.market.yfinance_client import (
    RateLimiter,
    clear_cache,
    get_current_price,
    get_historical_prices,
    get_stock_fundamentals,
)


def test_rate_limiter_throttling():
    limiter = RateLimiter(min_interval=0.1)
    start = time.time()
    limiter.wait()
    limiter.wait()
    elapsed = time.time() - start
    assert elapsed >= 0.09, f"RateLimiter did not throttle adequately: {elapsed}s"


def test_yfinance_client_caching():
    clear_cache()
    # Mock yfinance Ticker history
    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    df_fake = pd.DataFrame({
        "Open": [100.0 + i for i in range(10)],
        "High": [105.0 + i for i in range(10)],
        "Low": [95.0 + i for i in range(10)],
        "Close": [102.0 + i for i in range(10)],
        "Volume": [1000000 for _ in range(10)],
    }, index=dates)

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df_fake

    with patch("yfinance.Ticker", return_value=mock_ticker) as mock_yf:
        p1 = get_current_price("AAPL")
        assert p1 == 111.0
        assert mock_yf.call_count == 1

        # Second call should hit the cache without calling yfinance again
        p2 = get_current_price("AAPL")
        assert p2 == 111.0
        assert mock_yf.call_count == 1

        # Historical prices caching
        h1 = get_historical_prices("AAPL", period="1mo")
        assert h1 is not None
        assert len(h1) == 10
        assert mock_yf.call_count == 2

        h2 = get_historical_prices("AAPL", period="1mo")
        assert h2 is not None
        assert mock_yf.call_count == 2  # cached


def test_yfinance_fundamentals():
    clear_cache()
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame({"Close": [150.0]})
    mock_ticker.info = {
        "trailingPE": 28.5,
        "priceToBook": 4.2,
        "revenueGrowth": 0.18,
        "profitMargins": 0.22,
        "marketCap": 2500000000000,
        "shortName": "Apple Inc.",
    }

    with patch("yfinance.Ticker", return_value=mock_ticker):
        funds = get_stock_fundamentals("AAPL")
        assert funds["ticker"] == "AAPL"
        assert funds["price"] == 150.0
        assert funds["pe_ratio"] == 28.5
        assert funds["revenue_growth"] == 0.18
        assert funds["name"] == "Apple Inc."


def test_sector_definitions():
    assert len(SECTOR_ETFS) == 11
    assert "XLK" in SECTOR_ETFS
    assert "XLF" in SECTOR_ETFS
    assert "XLK" in SECTOR_STOCKS
    assert "AAPL" in SECTOR_STOCKS["XLK"]


def test_sector_intelligence_rating(tmp_path):
    intel = SectorIntelligence(cache_dir=tmp_path)

    # Generate synthetic prices for XLK and SPY
    dates = pd.date_range("2025-01-01", periods=250, freq="B")
    xlk_prices = pd.Series(np.linspace(150.0, 220.0, 250), index=dates)
    spy_prices = pd.Series(np.linspace(400.0, 500.0, 250), index=dates)

    df_xlk = pd.DataFrame({"Close": xlk_prices})
    df_spy = pd.DataFrame({"Close": spy_prices})

    with patch("quantizedalert.market.sector_intelligence.get_historical_prices") as mock_hist:
        def side_effect(ticker, period="1y"):
            if ticker == "XLK":
                return df_xlk
            if ticker == "SPY":
                return df_spy
            return None
        mock_hist.side_effect = side_effect

        rating = intel.rate_sector("XLK")
        assert isinstance(rating, SectorRating)
        assert rating.sector_etf == "XLK"
        assert rating.direction in ("LONG", "SHORT", "NEUTRAL")
        assert 0 <= rating.rating <= 100
        assert rating.above_sma_50 is True
        assert rating.above_sma_200 is True
        assert len(rating.top_picks) > 0


def test_us_workspace_configs():
    p_sp500 = Path("config/workspaces/sp500.yaml")
    p_tech = Path("config/workspaces/us_tech.yaml")

    assert p_sp500.exists(), "sp500.yaml missing"
    assert p_tech.exists(), "us_tech.yaml missing"

    cfg_sp500 = WorkspaceConfig.load(p_sp500)
    assert cfg_sp500.workspace_id == "sp500"
    assert cfg_sp500.region == "us"
    assert "AAPL" in cfg_sp500.instruments
    assert cfg_sp500.backtest.get("benchmark") == "SPY"

    cfg_tech = WorkspaceConfig.load(p_tech)
    assert cfg_tech.workspace_id == "us_tech"
    assert cfg_tech.region == "us"
    assert "NVDA" in cfg_tech.instruments

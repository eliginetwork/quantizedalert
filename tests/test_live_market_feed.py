"""Tests for UnifiedMarketDataFeed and RateLimitMonitor."""
import time
from unittest.mock import MagicMock, patch

import pytest
from quantizedalert.market.live_feed import (
    LivePriceDaemon,
    LiveQuote,
    RateLimitMonitor,
    UnifiedMarketDataFeed,
)


def test_rate_limit_monitor():
    monitor = RateLimitMonitor(limits={"test_prov": 5})
    assert monitor.can_request("test_prov") is True

    # Record 5 requests
    for _ in range(5):
        monitor.record_request("test_prov", success=True)

    assert monitor.can_request("test_prov") is False
    stats = monitor.get_stats()
    assert stats["test_prov"]["calls_last_minute"] == 5
    assert stats["test_prov"]["remaining_quota"] == 0
    assert stats["test_prov"]["status"] == "THROTTLED"


def test_live_quote_dataclass():
    quote = LiveQuote(
        symbol="NVDA",
        price=210.50,
        change=2.50,
        change_pct=1.20,
        source="alpaca_snapshot",
    )
    d = quote.to_dict()
    assert d["symbol"] == "NVDA"
    assert d["price"] == 210.50
    assert d["source"] == "alpaca_snapshot"
    assert "timestamp_iso" in d


def test_unified_feed_caching():
    feed = UnifiedMarketDataFeed(cache_ttl=2.0)
    fake_quote = LiveQuote(symbol="TEST", price=100.0, source="test")
    feed._set_cache("TEST", fake_quote)

    # First lookup: cache hit
    res = feed.get_quote("TEST")
    assert res is not None
    assert res.price == 100.0
    assert res.source == "test"


def test_ticker_tape_formatting():
    feed = UnifiedMarketDataFeed()
    feed._set_cache("UP_STOCK", LiveQuote(symbol="UP_STOCK", price=150.0, change_pct=2.5))
    feed._set_cache("DOWN_STOCK", LiveQuote(symbol="DOWN_STOCK", price=90.0, change_pct=-1.5))

    tape = feed.get_ticker_tape(symbols=["UP_STOCK", "DOWN_STOCK"])
    assert len(tape) == 2
    assert tape[0]["price_str"] == "$150.00"
    assert "▲ +2.50%" in tape[0]["change_str"]
    assert tape[0]["css_class"] == "ticker-up"

    assert tape[1]["price_str"] == "$90.00"
    assert "▼ -1.50%" in tape[1]["change_str"]
    assert tape[1]["css_class"] == "ticker-down"


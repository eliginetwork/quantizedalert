"""Tests for Stage 2: Multi-Factor Conviction Gating & Discovery."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from quantizedalert.alerts.intelligence import AlertIntelligence
from quantizedalert.config import AlertPrefs
from quantizedalert.discovery.conviction import ConvictionEngine, ConvictionScore
from quantizedalert.discovery.fundamentals import FundamentalAnalyzer, FundamentalRating
from quantizedalert.discovery.simplywallst import (
    CATEGORIES,
    SimplyWallStCandidate,
    SimplyWallStScraper,
)
from quantizedalert.schemas import AlertEvent, Severity


def test_simplywallst_candidate_model():
    cand = SimplyWallStCandidate(
        ticker="NVDA",
        name="NVIDIA Corporation",
        exchange="NasdaqGS",
        price=120.0,
        market_cap=3000000000000,
        category="High Growth Tech & AI",
        pe_ratio=45.0,
        pb_ratio=30.0,
        score_dividend=1,
        score_future=6,
        score_health=6,
        score_past=6,
        score_value=2,
    )
    assert cand.ticker == "NVDA"
    assert cand.total_snowflake_score == 21
    d = cand.to_dict()
    assert d["total_snowflake_score"] == 21
    assert d["ticker"] == "NVDA"


def test_simplywallst_categories():
    assert "undiscovered_gems" in CATEGORIES
    assert "high_growth_tech_ai" in CATEGORIES
    assert "high_insider_buying" in CATEGORIES
    assert CATEGORIES["undiscovered_gems"]["grid_view_id"] == 152


def test_simplywallst_scraper_live_or_fallback(tmp_path):
    scraper = SimplyWallStScraper(cache_dir=tmp_path)

    # Mock response from GraphQL
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "data": {
            "companyPredefinedScreenerResults": {
                "totalHits": 1,
                "companies": [
                    {
                        "tickerSymbol": "PLTR",
                        "name": "Palantir Technologies",
                        "exchangeSymbol": "NYSE",
                        "score": {"dividend": 0, "future": 5, "health": 6, "past": 4, "value": 2},
                        "analysisValue": {"marketCap": 60000000000, "lastSharePrice": 28.5, "pe": 65.0, "pb": 15.0},
                        "primaryIndustry": {"name": "Software"},
                    }
                ]
            }
        }
    }

    with patch.object(scraper.session, "post", return_value=fake_response):
        cands = scraper.fetch_category("high_growth_tech_ai", limit=5)
        assert len(cands) == 1
        assert cands[0].ticker == "PLTR"
        assert cands[0].price == 28.5
        assert cands[0].score_future == 5
        assert cands[0].total_snowflake_score == 17


def test_fundamental_analyzer():
    analyzer = FundamentalAnalyzer()

    # Strong company
    strong_metrics = {
        "revenue_growth": 0.25,
        "net_margin": 0.22,
        "debt_to_equity": 0.30,
        "current_ratio": 2.5,
        "roe": 0.28,
    }
    rating, score = analyzer.rate_fundamentals(strong_metrics)
    assert rating == FundamentalRating.STRONG
    assert score >= 80.0

    # Weak company
    weak_metrics = {
        "revenue_growth": -0.05,
        "net_margin": -0.15,
        "debt_to_equity": 3.5,
        "current_ratio": 0.7,
        "roe": -0.10,
    }
    rating_w, score_w = analyzer.rate_fundamentals(weak_metrics)
    assert rating_w == FundamentalRating.WEAK
    assert score_w <= 30.0


def test_conviction_engine_scoring():
    engine = ConvictionEngine(threshold=65.0)

    # 1. High conviction candidate
    score_high = engine.evaluate(
        ticker="NVDA",
        quant_score_raw=0.85,  # 85 pts
        fundamentals={
            "revenue_growth": 0.70,
            "net_margin": 0.50,
            "debt_to_equity": 0.25,
            "current_ratio": 3.0,
            "roe": 0.60,
        },
        sws_candidates=[{"ticker": "NVDA", "category": "High Growth Tech & AI", "score_health": 6}],
        sector_rating=75.0,
    )
    assert isinstance(score_high, ConvictionScore)
    assert score_high.passes_gate is True
    assert score_high.composite_conviction >= 75.0
    assert score_high.fundamental_rating == "STRONG"

    # 2. Low conviction candidate (poor fundamentals, dragging sector)
    score_low = engine.evaluate(
        ticker="JUNK",
        quant_score_raw=0.30,  # 30 pts
        fundamentals={
            "revenue_growth": -0.20,
            "net_margin": -0.10,
            "debt_to_equity": 4.0,
            "current_ratio": 0.6,
            "roe": -0.15,
        },
        sector_rating=35.0,
    )
    assert score_low.passes_gate is False
    assert score_low.composite_conviction < 50.0
    assert score_low.fundamental_rating == "WEAK"


def test_conviction_gating_in_alert_intelligence():
    store = MagicMock()
    store.recent_alerts.return_value = []
    store.alert_dedup_exists.return_value = False

    alerter = MagicMock()
    alerter.engine_source = "mock"
    alerter.dispatch.return_value = {"webhook": True}

    prefs = AlertPrefs(
        min_score=0.40,
        min_conviction=65.0,  # enforce 65 conviction gate
        channels=["webhook"],
    )

    intel = AlertIntelligence(store, alerter, prefs)

    # Event 1: High conviction (passes)
    e1 = AlertEvent(
        event_id="evt-1",
        workspace_id="test_ws",
        kind="signal_change",
        title="High conviction signal",
        body_md="Strong multi-factor setup",
        severity=Severity.HIGH,
        instruments=["NVDA"],
        components={"confidence": 0.9, "conviction": 80.0},
    )

    # Event 2: Low conviction (should be suppressed by conviction gate)
    e2 = AlertEvent(
        event_id="evt-2",
        workspace_id="test_ws",
        kind="signal_change",
        title="Low conviction signal",
        body_md="Noisy signal",
        severity=Severity.HIGH,
        instruments=["JUNK"],
        components={"confidence": 0.9, "conviction": 52.0},
    )

    decisions = intel.process([e1, e2], workspace_id="test_ws", asof="2026-09-12", held_instruments={"NVDA"})

    # Check decisions
    d_map = {d.event.event_id: d for d in decisions}
    assert d_map["evt-1"].deliver is True
    assert d_map["evt-2"].deliver is False
    assert "conviction 52.0 < min_conviction 65.0" in d_map["evt-2"].suppress_reason


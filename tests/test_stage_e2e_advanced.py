"""End-to-End Integration Test for Stages 1, 2, and 3.

Flow:
1. Stage 1: Query US Sector Intelligence for leading sectors (e.g. XLK vs SPY).
2. Stage 2: Discover candidates via SimplyWallSt, analyze SEC fundamentals & insider buying,
   and calculate Multi-Factor Conviction scores (0-100).
3. Stage 2 Gating: Low-conviction alerts are suppressed, high-conviction alerts are approved.
4. Stage 3: Auto-execute simulated paper trade on approved alert, update portfolio equity.
5. Stage 3 Learning: Record signals and evaluate Shadow Regret to close the feedback loop.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from quantizedalert.alerts.intelligence import AlertIntelligence
from quantizedalert.config import AlertPrefs
from quantizedalert.discovery.conviction import ConvictionEngine
from quantizedalert.discovery.simplywallst import SimplyWallStCandidate, SimplyWallStScraper
from quantizedalert.execution.paper_engine import PaperTradingEngine
from quantizedalert.learning.shadow_regret import RegretType, ShadowRegretEngine
from quantizedalert.market.sector_intelligence import SectorIntelligence
from quantizedalert.schemas import AlertEvent, Severity


def test_full_pipeline_stages_1_2_3_e2e(tmp_path):
    # ── STAGE 1: US Equities & Sector Expansion ──
    sector_dir = tmp_path / "sector"
    sector_intel = SectorIntelligence(cache_dir=sector_dir)

    dates = pd.date_range("2026-01-01", periods=100, freq="B")
    df_xlk = pd.DataFrame({"Close": [150.0 + (i * 0.8) for i in range(100)]}, index=dates)
    df_spy = pd.DataFrame({"Close": [400.0 + (i * 0.5) for i in range(100)]}, index=dates)

    with patch("quantizedalert.market.sector_intelligence.get_historical_prices") as mock_hist:
        def side_effect(ticker, period="1y"):
            if ticker == "XLK":
                return df_xlk
            if ticker == "SPY":
                return df_spy
            return None
        mock_hist.side_effect = side_effect

        rating_xlk = sector_intel.rate_sector("XLK")
        assert rating_xlk.sector_etf == "XLK"
        assert rating_xlk.rating > 50.0
        assert rating_xlk.direction == "LONG"

    # ── STAGE 2: Discovery & Multi-Factor Conviction Gating ──
    sws_dir = tmp_path / "sws"
    _scraper = SimplyWallStScraper(cache_dir=sws_dir)

    # Candidate 1: High growth tech winner
    cand_winner = SimplyWallStCandidate(
        ticker="NVDA",
        name="NVIDIA Corp",
        exchange="NasdaqGS",
        price=120.0,
        market_cap=3000000000000,
        category="High Growth Tech & AI",
        pe_ratio=45.0,
        score_future=6,
        score_health=6,
        score_past=6,
    )
    # Candidate 2: High risk weak candidate
    cand_loser = SimplyWallStCandidate(
        ticker="WEAK",
        name="Weak Speculative Corp",
        exchange="NasdaqCM",
        price=5.0,
        market_cap=50000000,
        category="Penny Growth",
        pe_ratio=-10.0,
        score_future=1,
        score_health=1,
        score_past=1,
    )

    conviction_engine = ConvictionEngine(threshold=65.0)

    score_winner = conviction_engine.evaluate(
        ticker="NVDA",
        quant_score_raw=0.88,
        fundamentals={"revenue_growth": 0.55, "net_margin": 0.40, "debt_to_equity": 0.2, "current_ratio": 2.5, "roe": 0.45},
        sws_candidates=[cand_winner.to_dict()],
        sector_rating=rating_xlk.rating,
    )
    assert score_winner.passes_gate is True
    assert score_winner.composite_conviction >= 70.0

    score_loser = conviction_engine.evaluate(
        ticker="WEAK",
        quant_score_raw=0.40,
        fundamentals={"revenue_growth": -0.15, "net_margin": -0.30, "debt_to_equity": 5.0, "current_ratio": 0.5, "roe": -0.20},
        sws_candidates=[cand_loser.to_dict()],
        sector_rating=35.0,
    )
    assert score_loser.passes_gate is False
    assert score_loser.composite_conviction < 50.0

    # Test Alert Intelligence Gating
    store = MagicMock()
    store.recent_alerts.return_value = []
    store.alert_dedup_exists.return_value = False
    alerter = MagicMock()
    alerter.engine_source = "mock"
    alerter.dispatch.return_value = {"webhook": True}

    prefs = AlertPrefs(min_score=0.40, min_conviction=65.0, channels=["webhook"])
    intel = AlertIntelligence(store, alerter, prefs)

    e_win = AlertEvent(
        event_id="evt-win",
        workspace_id="sp500",
        kind="signal_change",
        title="NVDA Breakout",
        body_md="High conviction",
        severity=Severity.HIGH,
        instruments=["NVDA"],
        components={"confidence": 0.9, "conviction": score_winner.composite_conviction},
    )
    e_lose = AlertEvent(
        event_id="evt-lose",
        workspace_id="sp500",
        kind="signal_change",
        title="WEAK Speculative",
        body_md="Low conviction",
        severity=Severity.HIGH,
        instruments=["WEAK"],
        components={"confidence": 0.5, "conviction": score_loser.composite_conviction},
    )

    decisions = intel.process([e_win, e_lose], workspace_id="sp500", asof="2026-09-12", held_instruments={"NVDA"})
    d_map = {d.event.event_id: d for d in decisions}

    assert d_map["evt-win"].deliver is True
    assert d_map["evt-lose"].deliver is False
    assert "min_conviction" in d_map["evt-lose"].suppress_reason

    # ── STAGE 3: Closed-Loop Paper Trading & Shadow Regret ──
    exec_dir = tmp_path / "execution"
    paper_engine = PaperTradingEngine(state_dir=exec_dir, initial_capital=100000.0)

    # Auto trade on approved high-conviction decision
    order = paper_engine.auto_paper_trade(d_map["evt-win"], current_price=120.0, target_allocation=0.05)
    assert order is not None
    assert order.ticker == "NVDA"
    assert order.status.value == "FILLED"
    assert "NVDA" in paper_engine.positions
    assert paper_engine.cash < 100000.0

    # Shadow Regret evaluation
    learn_dir = tmp_path / "learning"
    regret_engine = ShadowRegretEngine(state_dir=learn_dir)

    # Record both decisions (one delivered, one suppressed)
    regret_engine.record_signal("sig-win", "NVDA", "2026-09-12", score_winner.composite_conviction, delivered=True, entry_price=120.0, sector="XLK")
    regret_engine.record_signal("sig-lose", "WEAK", "2026-09-12", score_loser.composite_conviction, delivered=False, entry_price=5.0, sector="Speculative")

    # Simulate next-period prices: NVDA gained +10%, WEAK dropped -20%
    future_prices = {
        "NVDA": 132.0,  # +10% gain
        "WEAK": 4.0,    # -20% drop
    }

    report = regret_engine.evaluate_outcomes(current_prices=future_prices, benchmark_return_pct=2.0)
    assert report.total_signals == 2
    assert report.evaluated_signals == 2
    assert report.win_rate == 100.0         # NVDA was delivered and won
    assert report.false_positive_rate == 0.0
    assert report.false_negative_rate == 0.0 # WEAK dropped, so suppression was 100% correct (TRUE_NEGATIVE)

    outcomes = {o.ticker: o for o in regret_engine.outcomes}
    assert outcomes["NVDA"].regret_type == RegretType.TRUE_POSITIVE
    assert outcomes["WEAK"].regret_type == RegretType.TRUE_NEGATIVE

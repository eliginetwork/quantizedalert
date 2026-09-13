"""Tests for Stage 3: Closed-Loop Paper Trading & Shadow Regret."""
from __future__ import annotations

from quantizedalert.execution.models import OrderAction, OrderStatus, OrderType
from quantizedalert.execution.paper_engine import PaperTradingEngine
from quantizedalert.learning.shadow_regret import RegretType, ShadowRegretEngine
from quantizedalert.schemas import AlertDecision, AlertEvent, Severity


def test_paper_trading_buy_and_sell(tmp_path):
    engine = PaperTradingEngine(state_dir=tmp_path, initial_capital=50000.0, slippage_bps=10.0)

    # 1. Place a market BUY order
    order_buy = engine.place_order(
        workspace_id="test_ws",
        ticker="AAPL",
        action=OrderAction.BUY,
        quantity=100,
        market_price=150.0,
        reason="Testing paper buy",
    )
    assert order_buy.status == OrderStatus.FILLED
    assert order_buy.filled_quantity == 100
    # Slippage: 10 bps on 150 = 0.15, fill_price = 150.15
    assert order_buy.fill_price == 150.15
    expected_spent = 150.15 * 100
    assert abs(engine.cash - (50000.0 - expected_spent)) < 0.01

    assert "AAPL" in engine.positions
    pos = engine.positions["AAPL"]
    assert pos.quantity == 100
    assert pos.average_cost == 150.15

    # 2. Place a market SELL order at higher price (profit)
    order_sell = engine.place_order(
        workspace_id="test_ws",
        ticker="AAPL",
        action=OrderAction.SELL,
        quantity=50,
        market_price=160.0,
        reason="Testing paper sell partial",
    )
    assert order_sell.status == OrderStatus.FILLED
    assert order_sell.filled_quantity == 50
    # Slippage on sell: 160 * 0.001 = 0.16 -> 159.84
    assert order_sell.fill_price == 159.84
    assert engine.positions["AAPL"].quantity == 50
    assert engine.realized_pnl > 0.0


def test_paper_trading_insufficient_funds(tmp_path):
    engine = PaperTradingEngine(state_dir=tmp_path, initial_capital=1000.0)
    order = engine.place_order(
        workspace_id="test_ws",
        ticker="GOOGL",
        action=OrderAction.BUY,
        quantity=50,
        market_price=180.0,  # costs $9,000 > $1,000 cash
    )
    assert order.status == OrderStatus.REJECTED
    assert "Insufficient funds" in order.reason


def test_paper_trading_auto_trade_from_alert(tmp_path):
    engine = PaperTradingEngine(state_dir=tmp_path, initial_capital=100000.0)

    event = AlertEvent(
        event_id="evt-trade-1",
        workspace_id="test_ws",
        kind="signal_change",
        title="Breakout confirmed",
        body_md="Strong momentum",
        severity=Severity.HIGH,
        instruments=["MSFT"],
        components={"confidence": 0.95, "conviction": 85.0},
    )
    decision = AlertDecision(
        event=event,
        deliver=True,
        suppress_reason=None,
        channels=["webhook"],
        delivered={"webhook": True},
    )

    order = engine.auto_paper_trade(decision, current_price=400.0, target_allocation=0.05)
    assert order is not None
    assert order.ticker == "MSFT"
    assert order.action == OrderAction.BUY
    assert order.status == OrderStatus.FILLED
    assert order.quantity > 0
    assert "MSFT" in engine.positions


def test_shadow_regret_evaluation(tmp_path):
    engine = ShadowRegretEngine(state_dir=tmp_path)

    # Record 4 signals
    # 1. Delivered + Won -> TRUE_POSITIVE
    engine.record_signal("sig-1", "NVDA", "2026-09-01", 85.0, delivered=True, entry_price=100.0, sector="XLK")
    # 2. Delivered + Lost -> FALSE_POSITIVE
    engine.record_signal("sig-2", "TSLA", "2026-09-01", 75.0, delivered=True, entry_price=200.0, sector="XLY")
    # 3. Suppressed + Surged -> FALSE_NEGATIVE
    engine.record_signal("sig-3", "AMD", "2026-09-01", 50.0, delivered=False, entry_price=150.0, sector="XLK")
    # 4. Suppressed + Dropped -> TRUE_NEGATIVE
    engine.record_signal("sig-4", "INTC", "2026-09-01", 40.0, delivered=False, entry_price=30.0, sector="XLK")

    current_prices = {
        "NVDA": 115.0,  # +15%
        "TSLA": 180.0,  # -10%
        "AMD": 165.0,   # +10% (surged despite suppression)
        "INTC": 28.0,   # -6.7% (correctly suppressed)
    }

    report = engine.evaluate_outcomes(current_prices=current_prices, benchmark_return_pct=2.0)

    assert report.total_signals == 4
    assert report.evaluated_signals == 4
    # Delivered: 1 win out of 2 = 50%
    assert report.win_rate == 50.0
    assert report.false_positive_rate == 50.0
    # Suppressed: 1 surged out of 2 = 50%
    assert report.false_negative_rate == 50.0

    # Check individual outcomes
    outcomes = {o.ticker: o for o in engine.outcomes}
    assert outcomes["NVDA"].regret_type == RegretType.TRUE_POSITIVE
    assert outcomes["TSLA"].regret_type == RegretType.FALSE_POSITIVE
    assert outcomes["AMD"].regret_type == RegretType.FALSE_NEGATIVE
    assert outcomes["INTC"].regret_type == RegretType.TRUE_NEGATIVE
    assert report.total_regret_penalty > 0.0


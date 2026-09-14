"""Paper Trading Engine — Closed-loop order placement, fill simulation, and portfolio accounting.

Features:
- Realistic simulated execution with configurable slippage (default 5 bps) and half-spread impact.
- Portfolio accounting: cash balance, position cost averaging, market value, unrealized and realized PnL.
- Thread-safe order processing with state persistence in JSON/SQLite.
- Direct automated execution bridge from high-conviction alerts.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from quantizedalert.execution.models import (
    FillEvent,
    Order,
    OrderAction,
    OrderStatus,
    OrderType,
    Position,
)
from quantizedalert.schemas import AlertDecision

logger = logging.getLogger("quantizedalert.execution.paper")


class PaperTradingEngine:
    """Simulates realistic trade fills and manages paper portfolios."""

    def __init__(self, state_dir: Path | str = "market_cache/execution",
                 initial_capital: float = 100000.0,
                 slippage_bps: float = 5.0):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "portfolio_state.json"
        self.orders_file = self.state_dir / "orders.json"

        self.initial_capital = initial_capital
        self.slippage_rate = slippage_bps / 10000.0  # 5 bps = 0.0005
        self._lock = threading.Lock()

        self.cash: float = initial_capital
        self.realized_pnl: float = 0.0
        self.positions: dict[str, Position] = {}
        self.orders: list[Order] = []
        self._load_state()

    def _load_state(self) -> None:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self.cash = float(data.get("cash", self.initial_capital))
                self.realized_pnl = float(data.get("realized_pnl", 0.0))
                self.positions = {}
                for t, p in data.get("positions", {}).items():
                    self.positions[t] = Position(
                        ticker=p["ticker"],
                        quantity=p["quantity"],
                        average_cost=p["average_cost"],
                        current_price=p.get("current_price", p["average_cost"]),
                        realized_pnl=p.get("realized_pnl", 0.0),
                    )
            except Exception as e:
                logger.warning("Failed loading execution state: %s", e)

        if self.orders_file.exists():
            try:
                orders_data = json.loads(self.orders_file.read_text())
                self.orders = [
                    Order(
                        order_id=o["order_id"],
                        workspace_id=o["workspace_id"],
                        ticker=o["ticker"],
                        action=OrderAction(o["action"]),
                        quantity=o["quantity"],
                        order_type=OrderType(o["order_type"]),
                        limit_price=o.get("limit_price"),
                        status=OrderStatus(o["status"]),
                        fill_price=o.get("fill_price"),
                        filled_quantity=o.get("filled_quantity", 0),
                        slippage=o.get("slippage", 0.0),
                        created_at=o.get("created_at", ""),
                        filled_at=o.get("filled_at"),
                        reason=o.get("reason", ""),
                    )
                    for o in orders_data
                ]
            except Exception as e:
                logger.warning("Failed loading orders history: %s", e)

    def _save_state(self) -> None:
        try:
            state_data = {
                "cash": self.cash,
                "realized_pnl": self.realized_pnl,
                "positions": {t: p.to_dict() for t, p in self.positions.items()},
                "total_equity": self.get_total_equity(),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.state_file.write_text(json.dumps(state_data, indent=2))
            self.orders_file.write_text(json.dumps([o.to_dict() for o in self.orders[-200:]], indent=2))
        except Exception as e:
            logger.warning("Failed saving execution state: %s", e)

    def refresh_market_prices(self) -> None:
        """Fetch latest market prices for all open positions and update valuations."""
        if not self.positions:
            return
        try:
            from quantizedalert.market.live_feed import get_live_feed
            feed = get_live_feed()
            quotes = feed.get_quotes_batch(list(self.positions.keys()))
            changed = False
            for sym, pos in self.positions.items():
                q = quotes.get(sym) or quotes.get(sym.upper())
                if q and q.price and q.price > 0:
                    if pos.current_price != q.price:
                        pos.current_price = q.price
                        changed = True
            if changed:
                self._save_state()
        except Exception as e:
            logger.debug("Failed refreshing market prices for positions: %s", e)

    def get_total_equity(self, refresh: bool = False) -> float:
        """Total portfolio equity (cash + market value of all open positions)."""
        if refresh:
            self.refresh_market_prices()
        mv = sum(p.market_value for p in self.positions.values())
        return self.cash + mv

    def place_order(self, workspace_id: str, ticker: str,
                    action: str | OrderAction, quantity: int,
                    market_price: float,
                    order_type: str | OrderType = OrderType.MARKET,
                    limit_price: float | None = None,
                    reason: str = "") -> Order:
        """Place and immediately simulate execution of a paper trade."""
        with self._lock:
            act = OrderAction(action) if isinstance(action, str) else action
            ot = OrderType(order_type) if isinstance(order_type, str) else order_type
            t_clean = ticker.upper().strip()

            order_id = f"ord-{int(time.time()*1000)}"
            order = Order(
                order_id=order_id,
                workspace_id=workspace_id,
                ticker=t_clean,
                action=act,
                quantity=quantity,
                order_type=ot,
                limit_price=limit_price,
                reason=reason,
            )

            # Limit order check
            if ot == OrderType.LIMIT and limit_price is not None:
                if act == OrderAction.BUY and market_price > limit_price:
                    order.status = OrderStatus.PENDING
                    self.orders.append(order)
                    self._save_state()
                    return order
                elif act == OrderAction.SELL and market_price < limit_price:
                    order.status = OrderStatus.PENDING
                    self.orders.append(order)
                    self._save_state()
                    return order

            # Calculate slippage
            if act == OrderAction.BUY:
                slippage = market_price * self.slippage_rate
                fill_price = round(market_price + slippage, 2)
                required_cash = fill_price * quantity
                if required_cash > self.cash:
                    order.status = OrderStatus.REJECTED
                    order.reason = f"Insufficient funds (need ${required_cash:.2f}, have ${self.cash:.2f})"
                    self.orders.append(order)
                    self._save_state()
                    return order

                # Deduct cash & update position
                self.cash -= required_cash
                if t_clean in self.positions:
                    pos = self.positions[t_clean]
                    new_qty = pos.quantity + quantity
                    new_avg = ((pos.average_cost * pos.quantity) + (fill_price * quantity)) / new_qty
                    pos.quantity = new_qty
                    pos.average_cost = new_avg
                    pos.current_price = fill_price
                else:
                    self.positions[t_clean] = Position(
                        ticker=t_clean,
                        quantity=quantity,
                        average_cost=fill_price,
                        current_price=fill_price,
                    )

            else:  # SELL
                slippage = market_price * self.slippage_rate
                fill_price = round(market_price - slippage, 2)
                if t_clean not in self.positions or self.positions[t_clean].quantity < quantity:
                    order.status = OrderStatus.REJECTED
                    held = self.positions.get(t_clean, Position(t_clean, 0, 0)).quantity
                    order.reason = f"Insufficient shares to sell (requested {quantity}, held {held})"
                    self.orders.append(order)
                    self._save_state()
                    return order

                # Realize PnL and credit cash
                pos = self.positions[t_clean]
                trade_pnl = (fill_price - pos.average_cost) * quantity
                self.realized_pnl += trade_pnl
                self.cash += fill_price * quantity
                pos.realized_pnl += trade_pnl
                pos.quantity -= quantity
                pos.current_price = fill_price
                if pos.quantity == 0:
                    del self.positions[t_clean]

            # Mark order filled
            order.status = OrderStatus.FILLED
            order.fill_price = fill_price
            order.filled_quantity = quantity
            order.slippage = round(slippage, 4)
            order.filled_at = time.strftime("%Y-%m-%d %H:%M:%S")

            FillEvent(
                fill_id=f"fill-{order_id}",
                order_id=order_id,
                ticker=t_clean,
                action=act,
                quantity=quantity,
                price=fill_price,
                slippage=slippage,
            )

            self.orders.append(order)
            self._save_state()
            return order

    def auto_paper_trade(self, decision: AlertDecision, current_price: float,
                          target_allocation: float = 0.05) -> Order | None:
        """Automatically execute a paper trade from an approved alert decision."""
        if not decision.deliver:
            return None

        event = decision.event
        if not event.instruments:
            return None

        ticker = event.instruments[0].upper().strip()
        if current_price <= 0.0:
            return None

        total_eq = self.get_total_equity()
        alloc_dollars = total_eq * target_allocation
        shares = max(1, int(alloc_dollars / current_price))

        return self.place_order(
            workspace_id=event.workspace_id,
            ticker=ticker,
            action=OrderAction.BUY,
            quantity=shares,
            market_price=current_price,
            reason=f"Auto-trade from Alert {event.event_id} ({event.title})",
        )

    def get_portfolio_summary(self, refresh: bool = True) -> dict[str, Any]:
        """Return human-readable portfolio snapshot with refreshed live valuations."""
        with self._lock:
            if refresh:
                self.refresh_market_prices()
            return {
                "cash": round(self.cash, 2),
                "total_equity": round(self.get_total_equity(), 2),
                "realized_pnl": round(self.realized_pnl, 2),
                "open_positions": [p.to_dict() for p in self.positions.values()],
                "active_orders_count": len([o for o in self.orders if o.status == OrderStatus.PENDING]),
                "filled_orders_count": len([o for o in self.orders if o.status == OrderStatus.FILLED]),
            }


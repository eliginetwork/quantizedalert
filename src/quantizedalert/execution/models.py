"""Execution Data Models — Orders, Fills, Positions, and Portfolio State."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"


class OrderAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass
class Order:
    order_id: str
    workspace_id: str
    ticker: str
    action: OrderAction
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    status: OrderStatus = OrderStatus.PENDING
    fill_price: float | None = None
    filled_quantity: int = 0
    slippage: float = 0.0
    created_at: str = ""
    filled_at: str | None = None
    reason: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["action"] = self.action.value if isinstance(self.action, OrderAction) else self.action
        d["order_type"] = self.order_type.value if isinstance(self.order_type, OrderType) else self.order_type
        d["status"] = self.status.value if isinstance(self.status, OrderStatus) else self.status
        return d


@dataclass
class FillEvent:
    fill_id: str
    order_id: str
    ticker: str
    action: OrderAction
    quantity: int
    price: float
    slippage: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["action"] = self.action.value if isinstance(self.action, OrderAction) else self.action
        return d


@dataclass
class Position:
    ticker: str
    quantity: int
    average_cost: float
    current_price: float = 0.0
    realized_pnl: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.average_cost

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def return_pct(self) -> float:
        if self.cost_basis == 0.0:
            return 0.0
        return (self.unrealized_pnl / self.cost_basis) * 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "quantity": self.quantity,
            "average_cost": round(self.average_cost, 2),
            "current_price": round(self.current_price, 2),
            "market_value": round(self.market_value, 2),
            "cost_basis": round(self.cost_basis, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "return_pct": round(self.return_pct, 2),
        }


"""Unit and integration tests for Paper Execution Order API endpoints."""
import pytest
from pathlib import Path
from starlette.testclient import TestClient
from quantizedalert.config import PlatformConfig
from quantizedalert.dashboard.app import build_app
from quantizedalert.store import Store
from quantizedalert.execution.paper_engine import get_paper_engine


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTIZEDALERT_ENV", "testing")
    engine = get_paper_engine(state_dir=tmp_path / "exec_test")
    # Reset state for clean testing
    engine.cash = 100000.0
    engine.realized_pnl = 0.0
    engine.positions = {}
    engine.orders = []
    engine._save_state()

    pcfg = PlatformConfig(
        db_path=tmp_path / "test.db",
        workspace_dir=tmp_path / "workspaces",
        artifact_dir=tmp_path / "artifacts"
    )
    pcfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    pcfg.artifact_dir.mkdir(parents=True, exist_ok=True)
    store = Store(pcfg.db_path)
    app = build_app(pcfg, store=store)
    return TestClient(app)


def test_sparkline_api(client):
    res = client.get("/api/v1/market/sparkline?ticker=NVDA")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["symbol"] == "NVDA"
    assert "latest_price" in data
    assert "svg" in data
    assert "<svg" in data["svg"]


def test_place_order_buy_and_portfolio(client):
    # Buy 15 shares of NVDA
    payload = {
        "ticker": "NVDA",
        "action": "BUY",
        "quantity": 15,
        "order_type": "MARKET",
        "workspace_id": "alpha_gems"
    }
    res = client.post("/api/v1/execution/order", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["status"] == "FILLED"
    assert data["ticker"] == "NVDA"
    assert data["quantity"] == 15
    assert data["fill_price"] > 0
    assert data["slippage"] >= 0

    # Query orders history
    res_orders = client.get("/api/v1/execution/orders")
    assert res_orders.status_code == 200
    orders_data = res_orders.json()
    assert orders_data["ok"] is True
    assert len(orders_data["orders"]) >= 1
    assert orders_data["orders"][0]["ticker"] == "NVDA"

    # Query portfolio summary
    res_port = client.get("/api/v1/execution/portfolio")
    assert res_port.status_code == 200
    port_data = res_port.json()
    assert port_data["ok"] is True
    positions = port_data["portfolio"]["open_positions"]
    assert any(p["ticker"] == "NVDA" and p["quantity"] == 15 for p in positions)


def test_place_order_sell_partial(client):
    # Buy 20 ASTS
    client.post("/api/v1/execution/order", json={
        "ticker": "ASTS",
        "action": "BUY",
        "quantity": 20,
        "order_type": "MARKET"
    })
    # Sell 5 ASTS
    res_sell = client.post("/api/v1/execution/order", json={
        "ticker": "ASTS",
        "action": "SELL",
        "quantity": 5,
        "order_type": "MARKET"
    })
    assert res_sell.status_code == 200
    sell_data = res_sell.json()
    assert sell_data["status"] == "FILLED"
    assert sell_data["quantity"] == 5

    # Verify 15 ASTS remaining
    res_port = client.get("/api/v1/execution/portfolio")
    positions = res_port.json()["portfolio"]["open_positions"]
    asts_pos = next(p for p in positions if p["ticker"] == "ASTS")
    assert asts_pos["quantity"] == 15


def test_place_order_insufficient_funds(client):
    # Try to buy an absurd number of shares exceeding 100k cash
    payload = {
        "ticker": "NVDA",
        "action": "BUY",
        "quantity": 1000000,
        "order_type": "MARKET"
    }
    res = client.post("/api/v1/execution/order", json=payload)
    assert res.status_code == 400
    assert "Insufficient funds" in res.json()["detail"]

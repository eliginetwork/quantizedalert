"""Unit tests for Server-Sent Events (SSE) stream and custom user watchlists."""
import pytest
from starlette.testclient import TestClient

from quantizedalert.config import PlatformConfig
from quantizedalert.dashboard.app import build_app
from quantizedalert.store import Store


def test_store_user_watchlist(tmp_path):
    db_path = tmp_path / "test.db"
    store = Store(db_path)

    store.add_user_watchlist_ticker("user_1", "TSLA", target_price=250.0, notes="EV Breakout")
    store.add_user_watchlist_ticker("user_1", "AMD", target_price=180.0, notes="AI Chip Momentum")

    items = store.get_user_watchlist("user_1")
    assert len(items) == 2
    tickers = [it["ticker"] for it in items]
    assert "TSLA" in tickers
    assert "AMD" in tickers

    # Remove AMD
    store.remove_user_watchlist_ticker("user_1", "AMD")
    items_after = store.get_user_watchlist("user_1")
    assert len(items_after) == 1
    assert items_after[0]["ticker"] == "TSLA"


def test_watchlist_api_endpoints(tmp_path):
    pcfg = PlatformConfig(
        db_path=tmp_path / "test.db",
        workspace_dir=tmp_path / "workspaces",
        artifact_dir=tmp_path / "artifacts",
    )
    pcfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    pcfg.artifact_dir.mkdir(parents=True, exist_ok=True)
    store = Store(pcfg.db_path)
    app = build_app(pcfg, store=store)
    client = TestClient(app)

    # 1. Add Ticker
    res_add = client.post("/api/v1/user/watchlist", json={
        "clerk_id": "test_clerk_id",
        "ticker": "COIN",
        "target_price": 320.0,
        "notes": "Crypto Beta"
    })
    assert res_add.status_code == 200
    assert res_add.json()["ok"] is True
    assert res_add.json()["ticker"] == "COIN"

    # 2. Get Watchlist
    res_get = client.get("/api/v1/user/watchlist?clerk_id=test_clerk_id")
    assert res_get.status_code == 200
    get_data = res_get.json()
    assert get_data["ok"] is True
    assert len(get_data["items"]) == 1
    assert get_data["items"][0]["ticker"] == "COIN"
    assert "price" in get_data["items"][0]

    # 3. Delete Ticker
    res_del = client.request("DELETE", "/api/v1/user/watchlist", json={
        "clerk_id": "test_clerk_id",
        "ticker": "COIN"
    })
    assert res_del.status_code == 200
    assert res_del.json()["ok"] is True

    # 4. Verify empty
    res_empty = client.get("/api/v1/user/watchlist?clerk_id=test_clerk_id")
    assert len(res_empty.json()["items"]) == 0


def test_market_stream_sse_endpoint(tmp_path):
    pcfg = PlatformConfig(
        db_path=tmp_path / "test.db",
        workspace_dir=tmp_path / "workspaces",
        artifact_dir=tmp_path / "artifacts",
    )
    pcfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    pcfg.artifact_dir.mkdir(parents=True, exist_ok=True)
    store = Store(pcfg.db_path)
    app = build_app(pcfg, store=store)
    client = TestClient(app)

    # Connect to SSE stream with limit=1
    res = client.get("/api/v1/market/stream?limit=1")
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    assert "data:" in res.text
    assert "ticker_tape" in res.text

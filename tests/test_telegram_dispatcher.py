"""Unit tests for Automated Conviction Breakout Telegram Dispatcher and API."""
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

from quantizedalert.config import PlatformConfig
from quantizedalert.dashboard.app import build_app
from quantizedalert.store import Store
from quantizedalert.alerts.telegram_dispatcher import TelegramDispatcher, get_telegram_dispatcher


def test_telegram_dispatcher_cooldown():
    dispatcher = TelegramDispatcher(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        default_chat_id="7571610763",
        cooldown_sec=100.0,
    )
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        # First alert fires
        res1 = dispatcher.dispatch_breakout_alert(
            ticker="ASTS",
            price=58.79,
            change_pct=4.5,
            conviction_score=92.0,
            catalyst="FCC Approval",
            target_price=120.0,
            stop_loss=45.0,
            reason="Volume breakout",
            force=False,
        )
        assert res1["7571610763"] is True
        assert mock_post.call_count == 1

        # Second alert within cooldown is skipped
        res2 = dispatcher.dispatch_breakout_alert(
            ticker="ASTS",
            price=59.10,
            change_pct=4.8,
            conviction_score=93.0,
            force=False,
        )
        assert res2 == {}
        assert mock_post.call_count == 1

        # Third alert with force=True bypasses cooldown
        res3 = dispatcher.dispatch_breakout_alert(
            ticker="ASTS",
            price=59.50,
            change_pct=5.2,
            conviction_score=95.0,
            force=True,
        )
        assert res3["7571610763"] is True
        assert mock_post.call_count == 2


def test_store_telegram_chat_ids(tmp_path):
    db_path = tmp_path / "test_store.db"
    store = Store(db_path)

    # Insert user with clerk_id and telegram
    store.sync_user("user_clerk_1", "u1@fund.com", "User 1")
    store.update_user_telegram("user_clerk_1", "123456789", "user1_tg")

    store.sync_user("user_clerk_2", "u2@fund.com", "User 2")
    store.update_user_telegram("user_clerk_2", "987654321", "user2_tg")

    chat_ids = store.get_all_telegram_chat_ids()
    assert "123456789" in chat_ids
    assert "987654321" in chat_ids


def test_telegram_test_dispatch_api(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "mock_bot_token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "7571610763")

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

    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_post.return_value = mock_resp

        res = client.post("/api/v1/telegram/test_dispatch", json={"ticker": "ASTS", "chat_id": "7571610763"})
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["ticker"] == "ASTS"
        assert "7571610763" in data["results"]

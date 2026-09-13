"""Tests for Clerk Authentication and Telegram Alert Linkage."""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from quantizedalert.config import PlatformConfig
from quantizedalert.dashboard.app import build_app
from quantizedalert.store import Store


def test_user_store_lifecycle():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        store = Store(db_path)

        # 1. Sync new user
        u1 = store.sync_user("user_clerk_123", "trader@example.com", "Pro Trader")
        assert u1["clerk_id"] == "user_clerk_123"
        assert u1["email"] == "trader@example.com"
        assert u1["telegram_chat_id"] is None
        assert u1["plan"] == "free"

        # 2. Re-sync existing user updates last_login_at
        u2 = store.sync_user("user_clerk_123", "trader@example.com", "Pro Trader")
        assert u2["user_id"] == u1["user_id"]

        # 3. Link Telegram
        u3 = store.update_user_telegram("user_clerk_123", "987654321", "@protrader")
        assert u3 is not None
        assert u3["telegram_chat_id"] == "987654321"
        assert u3["telegram_username"] == "protrader"

        # 4. Lookup methods
        assert store.get_user_by_clerk_id("user_clerk_123")["email"] == "trader@example.com"
        assert store.get_user_by_telegram("987654321")["clerk_id"] == "user_clerk_123"
        assert len(store.list_users()) == 1


def test_auth_api_endpoints():
    with tempfile.TemporaryDirectory() as tmp:
        pcfg = PlatformConfig(
            db_path=Path(tmp) / "test.db",
            workspace_dir=Path(tmp) / "workspaces",
            artifact_dir=Path(tmp) / "artifacts"
        )
        store = Store(pcfg.db_path)
        app = build_app(pcfg, store=store)
        client = TestClient(app)

        # 1. POST /api/auth/sync
        r1 = client.post("/api/auth/sync", json={
            "clerk_id": "user_2test123",
            "email": "alpha@hedge.fund",
            "name": "Alpha Fund"
        })
        assert r1.status_code == 200
        data1 = r1.json()
        assert data1["ok"] is True
        assert data1["user"]["clerk_id"] == "user_2test123"
        assert data1["user"]["is_telegram_linked"] is False

        # 2. POST /api/auth/telegram
        r2 = client.post("/api/auth/telegram", json={
            "clerk_id": "user_2test123",
            "telegram_chat_id": "5551234",
            "telegram_username": "@quant_alpha"
        })
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["ok"] is True
        assert data2["user"]["telegram_chat_id"] == "5551234"
        assert data2["user"]["telegram_username"] == "quant_alpha"
        assert data2["user"]["is_telegram_linked"] is True

        # 3. GET /api/auth/user
        r3 = client.get("/api/auth/user?clerk_id=user_2test123")
        assert r3.status_code == 200
        data3 = r3.json()
        assert data3["user"]["telegram_chat_id"] == "5551234"


def test_dashboard_clerk_and_gating_rendered():
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = Path(tmp) / "workspaces"
        ws_dir.mkdir(parents=True, exist_ok=True)
        # Create alpha_gems workspace
        from quantizedalert.config import WorkspaceConfig
        wc = WorkspaceConfig(workspace_id="alpha_gems", instruments=["ASTS", "PLTR", "APP"])
        wc.save(ws_dir / "alpha_gems.yaml")

        pcfg = PlatformConfig(
            db_path=Path(tmp) / "test.db",
            workspace_dir=ws_dir,
            artifact_dir=Path(tmp) / "artifacts"
        )
        store = Store(pcfg.db_path)
        app = build_app(pcfg, store=store)
        client = TestClient(app)

        # 1. Check portal page
        r_portal = client.get("/")
        assert r_portal.status_code == 200
        assert "data-clerk-publishable-key=" in r_portal.text
        assert "clerk-auth-container" in r_portal.text

        # 2. Check alpha_gems page
        r_desk = client.get("/w/alpha_gems")
        assert r_desk.status_code == 200
        assert "telegram-link-banner" in r_desk.text
        assert "telegram-modal" in r_desk.text
        assert "gated-row blurred" in r_desk.text
        assert "gem-gate-banner" in r_desk.text


"""Unit tests for Macro Market Regime & Volatility Gauge."""
import pytest
from starlette.testclient import TestClient

from quantizedalert.config import PlatformConfig
from quantizedalert.dashboard.app import build_app
from quantizedalert.store import Store
from quantizedalert.analysis.macro_regime import MacroRegimeEngine, get_macro_regime_engine


def test_macro_regime_calculation():
    engine = MacroRegimeEngine(cache_ttl_sec=0.0)
    fake_sectors = [
        {"etf": "XLK", "direction": "BULLISH", "mom_1m": 0.05},
        {"etf": "XLE", "direction": "BULLISH", "mom_1m": 0.08},
        {"etf": "XLF", "direction": "BEARISH", "mom_1m": -0.02},
    ]
    snapshot = engine.calculate_regime(sectors=fake_sectors)
    assert 0.0 <= snapshot.score <= 100.0
    assert snapshot.regime_label in [
        "AGGRESSIVE RISK-ON", "MODERATE EXPANSION", "NEUTRAL ROTATION", "DEFENSIVE / VOLATILE", "EXTREME RISK-OFF"
    ]
    assert "<svg" in snapshot.gauge_svg
    assert "</svg>" in snapshot.gauge_svg
    assert "viewBox=\"0 0 120 65\"" in snapshot.gauge_svg


def test_macro_gauge_svg_bounds():
    engine = MacroRegimeEngine()
    svg_0 = engine.generate_gauge_svg(0.0)
    svg_50 = engine.generate_gauge_svg(50.0)
    svg_100 = engine.generate_gauge_svg(100.0)

    for svg in [svg_0, svg_50, svg_100]:
        assert "<line" in svg
        assert "<circle" in svg
        assert "<text" in svg


def test_macro_regime_api(tmp_path):
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

    res = client.get("/api/v1/macro/regime")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "regime" in data
    regime = data["regime"]
    assert "score" in regime
    assert "regime_label" in regime
    assert "gauge_svg" in regime
    assert "<svg" in regime["gauge_svg"]

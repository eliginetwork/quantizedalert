"""Unit tests for Multi-Strategy Walk-Forward Comparison Engine."""
import pytest
from starlette.testclient import TestClient

from quantizedalert.config import PlatformConfig
from quantizedalert.dashboard.app import build_app
from quantizedalert.store import Store
from quantizedalert.analysis.strategy_compare import StrategyComparisonEngine, get_strategy_compare_engine


def test_strategy_compare_data():
    engine = StrategyComparisonEngine(initial_capital=100000.0)
    data = engine.get_comparison_data(days=45)
    assert data["days"] == 45
    assert len(data["strategies"]) == 3
    tags = [s["tag"] for s in data["strategies"]]
    assert "GEM" in tags
    assert "RIDGE" in tags
    assert "SPY" in tags
    assert "<svg" in data["chart_svg"]
    assert "</svg>" in data["chart_svg"]


def test_strategy_compare_chart_svg():
    engine = StrategyComparisonEngine()
    curves = [
        [100.0, 105.0, 110.0, 118.0],
        [100.0, 101.0, 103.0, 106.0],
    ]
    svg = engine.generate_comparison_chart_svg(curves, ["#00E676", "#D4AF37"])
    assert "<polyline" in svg
    assert "<circle" in svg
    assert "viewBox=\"0 0 760 240\"" in svg


def test_strategy_compare_api(tmp_path):
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

    res = client.get("/api/v1/backtest/compare?days=30")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "comparison" in data
    assert len(data["comparison"]["strategies"]) == 3

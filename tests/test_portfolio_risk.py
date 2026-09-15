"""Unit tests for Portfolio Risk Analytics Matrix."""
import pytest
from starlette.testclient import TestClient

from quantizedalert.config import PlatformConfig
from quantizedalert.dashboard.app import build_app
from quantizedalert.store import Store
from quantizedalert.analysis.portfolio_risk import PortfolioRiskEngine, get_portfolio_risk_engine


def test_portfolio_risk_calculation():
    engine = PortfolioRiskEngine(risk_free_rate=0.045)
    sample_summary = {
        "cash": 30000.0,
        "total_equity": 100000.0,
        "open_positions": [
            {"ticker": "NVDA", "quantity": 100, "market_value": 35000.0},
            {"ticker": "ASTS", "quantity": 400, "market_value": 20000.0},
            {"ticker": "XOM", "quantity": 100, "market_value": 15000.0},
        ]
    }
    rm = engine.compute_risk_matrix(sample_summary)
    assert rm.total_equity == 100000.0
    assert rm.cash == 30000.0
    assert rm.var_95_daily_amount > 0.0
    assert rm.var_95_daily_pct > 0.0
    assert rm.portfolio_beta > 0.5
    assert rm.sharpe_ratio > 0.0
    assert rm.sortino_ratio > 0.0
    assert len(rm.allocations) == 4  # Cash + 3 positions
    assert rm.top_concentration_asset in ["NVDA", "CASH"]


def test_portfolio_risk_all_cash():
    engine = PortfolioRiskEngine()
    summary = {
        "cash": 100000.0,
        "total_equity": 100000.0,
        "open_positions": []
    }
    rm = engine.compute_risk_matrix(summary)
    assert rm.portfolio_beta == 0.0
    assert rm.top_concentration_asset == "CASH"
    assert rm.concentration_status == "HEALTHY DIVERSIFICATION"


def test_portfolio_risk_api(tmp_path):
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

    res = client.get("/api/v1/execution/risk_matrix")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "risk_matrix" in data
    rm = data["risk_matrix"]
    assert "var_95_daily_amount" in rm
    assert "portfolio_beta" in rm
    assert "sharpe_ratio" in rm
    assert "sortino_ratio" in rm

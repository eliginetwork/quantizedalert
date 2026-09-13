"""Unit tests for GemRadar multi-bagger potential discovery and Social Formatter."""
from __future__ import annotations

from pathlib import Path

from quantizedalert.alerts.social_formatter import (
    calculate_trade_levels,
    format_x_post,
    generate_social_payload,
)
from quantizedalert.config import WorkspaceConfig
from quantizedalert.discovery.gem_radar import CURATED_GEM_UNIVERSE, GemRadar


def test_gem_radar_calculation(tmp_path: Path):
    radar = GemRadar(cache_dir=tmp_path / "cache")
    mpi, catalysts = radar.calculate_mpi(
        rev_growth=120.0,
        gross_margin=75.0,
        rvol=3.2,
        insider_score=85.0,
        sws_snowflake=23,
        cross_ref_count=3,
    )
    assert 80.0 <= mpi <= 100.0
    assert "HYPER_GROWTH_100PCT" in catalysts
    assert "ELITE_GROSS_MARGIN" in catalysts
    assert "TRIPLE_SCREENER_CONFLUENCE" in catalysts
    assert "WHALE_VOLUME_BREAKOUT" in catalysts
    assert "HEAVY_INSIDER_BUYING" in catalysts


def test_gem_radar_scan(tmp_path: Path):
    radar = GemRadar(cache_dir=tmp_path / "cache")
    gems = radar.scan_gem_universe()
    assert len(gems) >= len(CURATED_GEM_UNIVERSE)
    top_gem = gems[0]
    assert top_gem.mpi_score >= 70.0
    assert top_gem.market_cap >= 300e6
    assert len(top_gem.market_cap_str) > 0


def test_trade_levels_calculation():
    levels = calculate_trade_levels(price=50.0, stop_pct=0.08, target1_pct=0.32)
    assert levels["price"] == 50.0
    assert levels["stop_loss"] == "$46.00"
    assert levels["target1"] == "$66.00"
    assert "x" in levels["rr_ratio"]


def test_social_formatter_output():
    tweet = format_x_post(
        ticker="ASTS",
        name="AST SpaceMobile Inc.",
        sector="Space / Telecom",
        market_cap_str="$5.8B",
        price=28.50,
        rev_growth=140.0,
        gross_margin=68.0,
        rvol=3.4,
        mpi_score=94.5,
        catalysts=["HYPER_GROWTH_100PCT", "WHALE_VOLUME_BREAKOUT"],
        quant_score=0.88,
        thesis="Commercial direct-to-cell satellite service launch.",
    )
    assert "$ASTS" in tweet
    assert "AST SpaceMobile" in tweet
    assert "Entry Zone:" in tweet
    assert "Invalidation / Stop:" in tweet
    assert "Target 1:" in tweet
    assert "MPI" in tweet
    assert "#FinTwit" in tweet

    payload = generate_social_payload({
        "ticker": "PLTR",
        "name": "Palantir Technologies",
        "price": 36.0,
        "market_cap_str": "$24.5B",
        "revenue_growth": 42.0,
        "gross_margin": 81.0,
        "relative_volume": 2.2,
        "mpi_score": 91.0,
    })
    assert payload["ticker"] == "PLTR"
    assert len(payload["tweet_text"]) > 50


def test_alpha_gems_workspace_config():
    p = Path("config/workspaces/alpha_gems.yaml")
    assert p.exists()
    wc = WorkspaceConfig.load(str(p))
    assert wc.workspace_id == "alpha_gems"
    assert "ASTS" in wc.instruments
    assert "PLTR" in wc.instruments
    assert len(wc.instruments) >= 15
    assert wc.alerts.min_conviction == 68.0

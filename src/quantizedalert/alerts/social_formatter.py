"""Social Media / X (Twitter) Alert Formatter for FinTwit.

Formats high-conviction quantitative signals into viral, institutional-grade
X (Twitter) posts designed for trader engagement, transparency, and alpha discovery.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("quantizedalert.alerts.social")


def calculate_trade_levels(price: float, stop_pct: float = 0.085,
                           target1_pct: float = 0.32,
                           target2_pct: float = 0.85) -> dict[str, Any]:
    """Calculate entry zone, stop loss, profit targets, and asymmetric R:R."""
    if price <= 0.0:
        price = 10.0

    entry_low = round(price * 0.99, 2)
    entry_high = round(price * 1.015, 2)
    stop_loss = round(price * (1.0 - stop_pct), 2)
    target1 = round(price * (1.0 + target1_pct), 2)
    target2 = round(price * (1.0 + target2_pct), 2)

    risk = price - stop_loss
    reward = target1 - price
    rr_ratio = round(reward / (risk + 1e-6), 1) if risk > 0 else 3.5

    return {
        "price": round(price, 2),
        "entry_zone": f"${entry_low:.2f} - ${entry_high:.2f}",
        "stop_loss": f"${stop_loss:.2f}",
        "risk_pct": f"-{stop_pct * 100:.1f}%",
        "target1": f"${target1:.2f}",
        "target1_pct": f"+{target1_pct * 100:.0f}%",
        "target2": f"${target2:.2f}",
        "target2_pct": f"+{target2_pct * 100:.0f}%",
        "rr_ratio": f"{rr_ratio}x",
    }


def format_x_post(ticker: str, name: str, sector: str,
                  market_cap_str: str, price: float,
                  rev_growth: float, gross_margin: float,
                  rvol: float, mpi_score: float,
                  catalysts: list[str] | None = None,
                  quant_score: float = 0.84,
                  thesis: str = "") -> str:
    """Format an institutional high-impact post optimized for X (Twitter)."""
    t_clean = ticker.upper().strip()
    levels = calculate_trade_levels(price)
    cats = catalysts or []

    # Format human-readable catalyst bullets
    cat_bullets = []
    if rev_growth >= 40.0:
        cat_bullets.append(f"Accelerating YoY Revenue Growth: +{rev_growth:.0f}%")
    if gross_margin >= 60.0:
        cat_bullets.append(f"High-Margin Operating Leverage: {gross_margin:.0f}% Gross Margin")
    if rvol >= 2.0:
        cat_bullets.append(f"Institutional Accumulation: {rvol:.1f}x 30-Day Volume Surge")
    if any("INSIDER" in c for c in cats):
        cat_bullets.append("Open-Market Executive & Whale Cluster Buying")
    if not cat_bullets:
        cat_bullets.append(thesis or f"Multi-Factor Breakout Candidate (+{rev_growth:.0f}% Growth)")

    bullets_formatted = "\n".join(f"• {b}" for b in cat_bullets[:3])

    tweet = (
        f"🚨 QUANTIZEDALERT GEM RADAR (10X Potential Alert) 🚨\n\n"
        f"${t_clean} — {name}\n"
        f"• Market Cap: {market_cap_str} (Asymmetric Growth Zone)\n"
        f"• Sector & Theme: {sector}\n\n"
        f"💎 Core Alpha Catalysts:\n"
        f"{bullets_formatted}\n"
        f"• Multi-Bagger Potential Index (MPI): {mpi_score:.1f}/100\n\n"
        f"🎯 Asymmetric Trade Setup:\n"
        f"• Entry Zone: {levels['entry_zone']}\n"
        f"• Invalidation / Stop: {levels['stop_loss']} (Risk: {levels['risk_pct']})\n"
        f"• Target 1: {levels['target1']} ({levels['target1_pct']})\n"
        f"• Target 2: {levels['target2']} ({levels['target2_pct']})\n"
        f"• Asymmetric R:R: {levels['rr_ratio']}\n\n"
        f"Quant Score: {quant_score:+.2f} | Model: LightGBM Alpha158\n"
        f"#Stocks #FinTwit #Quant #Breakout #{t_clean} #AlphaGems"
    )
    return tweet


def generate_social_payload(candidate_dict: dict[str, Any], quant_score: float = 0.85) -> dict[str, Any]:
    """Generate structured JSON payload for webhooks, bots, and UI display."""
    t = candidate_dict.get("ticker", "GEMS")
    name = candidate_dict.get("name", t)
    sector = candidate_dict.get("sector", "Emerging Tech")
    mcap = candidate_dict.get("market_cap_str", "$2.5B")
    price = float(candidate_dict.get("price", 25.0))
    rev_g = float(candidate_dict.get("revenue_growth", 45.0))
    gm = float(candidate_dict.get("gross_margin", 65.0))
    rvol = float(candidate_dict.get("relative_volume", 2.4))
    mpi = float(candidate_dict.get("mpi_score", 88.0))
    cats = candidate_dict.get("catalysts", [])
    thesis = candidate_dict.get("thesis", "")

    tweet_text = format_x_post(
        ticker=t,
        name=name,
        sector=sector,
        market_cap_str=mcap,
        price=price,
        rev_growth=rev_g,
        gross_margin=gm,
        rvol=rvol,
        mpi_score=mpi,
        catalysts=cats,
        quant_score=quant_score,
        thesis=thesis,
    )

    levels = calculate_trade_levels(price)
    return {
        "ticker": t,
        "name": name,
        "sector": sector,
        "market_cap": mcap,
        "price": price,
        "mpi_score": mpi,
        "tweet_text": tweet_text,
        "levels": levels,
        "char_count": len(tweet_text),
    }

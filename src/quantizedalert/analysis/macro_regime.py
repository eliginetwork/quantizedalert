"""Macro Market Regime & Volatility Gauge Engine.

Synthesizes benchmark index trends (SPY/QQQ), 11 GICS sector momentum breadth,
and market volatility into an institutional 0-100 Risk-On/Risk-Off gauge.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger("quantizedalert.macro")


@dataclass
class MacroRegimeSnapshot:
    score: float
    regime_label: str
    color: str
    css_class: str
    trend_score: float
    breadth_score: float
    volatility_score: float
    recommended_exposure: str
    gauge_svg: str
    asof: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MacroRegimeEngine:
    """Computes macroeconomic regime scoring and generates visual gauge instrumentation."""

    def __init__(self, cache_ttl_sec: float = 60.0):
        self.cache_ttl_sec = cache_ttl_sec
        self._cached_snapshot: MacroRegimeSnapshot | None = None
        self._last_calc_time: float = 0.0

    def generate_gauge_svg(self, score: float, color: str = "#D4AF37") -> str:
        """Render a luxury Wall Street 180-degree semi-circular speedometer SVG gauge."""
        score_clamped = max(0.0, min(100.0, score))
        # Needle angle: 0 score = -90 deg (left), 100 score = +90 deg (right)
        angle_rad = (score_clamped / 100.0) * math.pi - (math.pi / 2.0)
        needle_len = 38
        cx, cy = 60, 52
        nx = cx + needle_len * math.sin(angle_rad + math.pi / 2.0)
        ny = cy - needle_len * math.cos(angle_rad + math.pi / 2.0)

        # SVG arc path for gauge background (radius=42, from angle pi to 0)
        # 180 deg arc from (18, 52) to (102, 52)
        return (
            f'<svg width="120" height="65" viewBox="0 0 120 65" fill="none" xmlns="http://www.w3.org/2000/svg" style="overflow:visible;">'
            f'<defs>'
            f'<linearGradient id="gaugeGrad" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0%" stop-color="#FF3366" />'
            f'<stop offset="35%" stop-color="#FF9900" />'
            f'<stop offset="65%" stop-color="#D4AF37" />'
            f'<stop offset="100%" stop-color="#00E676" />'
            f'</linearGradient>'
            f'<filter id="glow" x="-20%" y="-20%" width="140%" height="140%">'
            f'<feGaussianBlur stdDeviation="3" result="blur" />'
            f'<feComposite in="SourceGraphic" in2="blur" operator="over" />'
            f'</filter>'
            f'</defs>'
            f'<!-- Gauge Track Background -->'
            f'<path d="M 18 52 A 42 42 0 0 1 102 52" stroke="rgba(255,255,255,0.08)" stroke-width="7" stroke-linecap="round" fill="none"/>'
            f'<!-- Gauge Track Colored -->'
            f'<path d="M 18 52 A 42 42 0 0 1 102 52" stroke="url(#gaugeGrad)" stroke-width="7" stroke-linecap="round" fill="none" opacity="0.85"/>'
            f'<!-- Center Hub -->'
            f'<circle cx="{cx}" cy="{cy}" r="5" fill="{color}" filter="url(#glow)"/>'
            f'<circle cx="{cx}" cy="{cy}" r="3" fill="#05070B"/>'
            f'<!-- Needle -->'
            f'<line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}" stroke="{color}" stroke-width="2.5" stroke-linecap="round" filter="url(#glow)"/>'
            f'<!-- Score Text -->'
            f'<text x="{cx}" y="63" text-anchor="middle" font-family="JetBrains Mono, monospace" font-size="11" font-weight="700" fill="{color}">{score:.0f}</text>'
            f'</svg>'
        )

    def calculate_regime(self, feed: Any = None, sectors: list[dict] | None = None) -> MacroRegimeSnapshot:
        """Calculate market regime snapshot with in-memory caching."""
        now = time.time()
        if self._cached_snapshot and (now - self._last_calc_time < self.cache_ttl_sec):
            return self._cached_snapshot

        trend_score = 30.0
        breadth_score = 22.0
        volatility_score = 24.0

        try:
            if feed is None:
                from quantizedalert.market.live_feed import get_live_feed
                feed = get_live_feed()

            # 1. Index Trend (SPY / QQQ)
            spy = feed.get_quote("SPY")
            qqq = feed.get_quote("QQQ")
            spy_chg = spy.change_pct if (spy and spy.change_pct is not None) else 0.4
            qqq_chg = qqq.change_pct if (qqq and qqq.change_pct is not None) else 0.7

            avg_idx_chg = (spy_chg + qqq_chg) / 2.0
            # Base 25, +5 per 1% index gain up to 40 max
            trend_score = max(5.0, min(40.0, 25.0 + (avg_idx_chg * 7.5)))

            # 2. Sector Breadth (11 GICS sectors)
            if sectors:
                pos_sectors = sum(1 for s in sectors if s.get("direction") == "BULLISH" or s.get("mom_1m", 0) > 0)
                breadth_ratio = pos_sectors / max(1, len(sectors))
                breadth_score = max(5.0, min(30.0, breadth_ratio * 30.0))
            else:
                breadth_score = 20.0

            # 3. Volatility / Relative Volatility Ratio
            # If indices down hard, volatility score drops
            if avg_idx_chg < -1.5:
                volatility_score = 8.0
            elif avg_idx_chg < 0:
                volatility_score = 16.0
            else:
                volatility_score = min(30.0, 24.0 + (avg_idx_chg * 4.0))

        except Exception as e:
            logger.warning("Error computing real-time macro regime: %s", e)

        total_score = round(trend_score + breadth_score + volatility_score, 1)
        total_score = max(0.0, min(100.0, total_score))

        if total_score >= 80.0:
            regime_label = "AGGRESSIVE RISK-ON"
            color = "#00E676"
            css_class = "pos"
            exposure = "100% Capital Deployment · Maximum Alpha Growth"
        elif total_score >= 60.0:
            regime_label = "MODERATE EXPANSION"
            color = "#D4AF37"
            css_class = "pos"
            exposure = "80-90% Allocation · Selective Growth Breakouts"
        elif total_score >= 40.0:
            regime_label = "NEUTRAL ROTATION"
            color = "#E5A93C"
            css_class = "neu"
            exposure = "60-70% Allocation · Tight Trailing Stops"
        elif total_score >= 25.0:
            regime_label = "DEFENSIVE / VOLATILE"
            color = "#FF9900"
            css_class = "neg"
            exposure = "30-50% Allocation · Capital Preservation"
        else:
            regime_label = "EXTREME RISK-OFF"
            color = "#FF3366"
            css_class = "neg"
            exposure = "Cash Heavy (10-20%) · High Conviction Gates Only"

        gauge_svg = self.generate_gauge_svg(total_score, color=color)

        snapshot = MacroRegimeSnapshot(
            score=total_score,
            regime_label=regime_label,
            color=color,
            css_class=css_class,
            trend_score=round(trend_score, 1),
            breadth_score=round(breadth_score, 1),
            volatility_score=round(volatility_score, 1),
            recommended_exposure=exposure,
            gauge_svg=gauge_svg,
            asof=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._cached_snapshot = snapshot
        self._last_calc_time = now
        return snapshot


_macro_engine_instance: MacroRegimeEngine | None = None


def get_macro_regime_engine() -> MacroRegimeEngine:
    global _macro_engine_instance
    if _macro_engine_instance is None:
        _macro_engine_instance = MacroRegimeEngine()
    return _macro_engine_instance

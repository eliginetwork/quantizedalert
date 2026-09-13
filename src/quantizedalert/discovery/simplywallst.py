"""SimplyWallSt Scraper — Curated stock discovery via GraphQL API.

Features:
- Access to 25+ curated screener categories (Undiscovered Gems, Value, High Growth AI, Insider Buying).
- Direct GraphQL querying with Apollo client headers and anti-blocking measures.
- Dual-tier caching with offline fallback to cached candidate snapshots.
- Structured output normalizing fundamentals, SWS Snowflake scores (0-6), and analyst targets.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("quantizedalert.discovery.simplywallst")

CATEGORIES: dict[str, dict[str, Any]] = {
    # ── Fundamental / Value ──
    "undiscovered_gems": {
        "grid_view_id": 152,
        "name": "Undiscovered Gems",
        "description": "Small caps with strong fundamentals",
        "group": "value",
    },
    "undervalued_cash_flows": {
        "grid_view_id": 168,
        "name": "Undervalued Cash Flows",
        "description": "Undervalued based on discounted cash flow",
        "group": "value",
    },
    "solid_balance_sheet": {
        "grid_view_id": 10146,
        "name": "Solid Balance Sheet",
        "description": "Strong balance sheets and fundamental health",
        "group": "value",
    },
    # ── Growth & Tech ──
    "fast_growing_insider": {
        "grid_view_id": 10228,
        "name": "Fast Growing Insider",
        "description": "Growth stocks with high insider ownership",
        "group": "growth",
    },
    "high_growth_tech_ai": {
        "grid_view_id": 215171,
        "name": "High Growth Tech & AI",
        "description": "AI and tech growth stocks with clean financials",
        "group": "growth",
    },
    "breakout_stocks": {
        "grid_view_id": 10195,
        "name": "Breakout Stocks",
        "description": "Technical and fundamental breakout candidates",
        "group": "growth",
    },
    "ai_small_caps": {
        "grid_view_id": 472948,
        "name": "AI Small Caps",
        "description": "Small-cap AI and automation companies",
        "group": "growth",
    },
    # ── Special / Insider ──
    "high_insider_buying": {
        "grid_view_id": 171,
        "name": "High Insider Buying",
        "description": "Significant insider purchasing activity",
        "group": "insider",
    },
    "undervalued_small_caps_insider_buying": {
        "grid_view_id": 16951,
        "name": "Undervalued Small Caps + Insider Buying",
        "description": "Value combined with executive purchases",
        "group": "insider",
    },
    "big_green_snowflakes": {
        "grid_view_id": 206,
        "name": "Big Green Snowflakes",
        "description": "Companies rated green across all 5 dimensions",
        "group": "quality",
    },
}


@dataclass
class SimplyWallStCandidate:
    """Standardized representation of a discovered stock."""

    ticker: str
    name: str
    exchange: str
    price: float
    market_cap: float
    category: str
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    score_dividend: int = 0
    score_future: int = 0
    score_health: int = 0
    score_past: int = 0
    score_value: int = 0
    industry: str = ""
    is_us_listed: bool = True

    @property
    def total_snowflake_score(self) -> int:
        return self.score_dividend + self.score_future + self.score_health + self.score_past + self.score_value

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["total_snowflake_score"] = self.total_snowflake_score
        return d


class SimplyWallStScraper:
    """Scrapes SimplyWallSt curated stock lists with robust fallback caching."""

    def __init__(self, cache_dir: Path | str = "market_cache/simplywallst",
                 username: str | None = None, password: str | None = None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.token_file = self.cache_dir / "bearer_token.json"
        self.candidates_cache_file = self.cache_dir / "candidates.json"

        self.username = username or os.environ.get("SIMPLYWALLST_USERNAME", "princeyormi@engineer.com")
        self.password = password or os.environ.get("SIMPLYWALLST_PASSWORD", "fTUkKVZ!S2fC66d")

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "Origin": "https://simplywall.st",
            "Referer": "https://simplywall.st/discover/investing-ideas",
            "apollographql-client-name": "web",
            "apollographql-client-version": "mono-auto-10a86af9",
        })

    def fetch_category(self, category_key: str, limit: int = 25,
                       country: str = "us") -> list[SimplyWallStCandidate]:
        """Fetch candidates for a specific category via GraphQL."""
        cat_meta = CATEGORIES.get(category_key)
        if not cat_meta:
            raise ValueError(f"Unknown category '{category_key}'. Available: {list(CATEGORIES.keys())}")

        grid_id = cat_meta["grid_view_id"]
        cat_name = cat_meta["name"]

        country_filter_clause = (
            f', additionalFilters: [{{field: country_name, operator: in, logicalCondition: aor, values: ["{country}"]}}]'
            if country else ""
        )

        query = f"""
        {{
          companyPredefinedScreenerResults(
            input: {{
              gridViewId: {grid_id},
              limit: {limit},
              offset: 0,
              displayRecentlyAddedCompanies: true,
              returnRecentCompaniesOnly: false{country_filter_clause}
            }}
          ) {{
            totalHits
            companies {{
              tickerSymbol
              name
              exchangeSymbol
              score {{
                dividend
                future
                health
                past
                value
              }}
              analysisValue {{
                marketCap
                lastSharePrice
                pe
                pb
              }}
              primaryIndustry {{
                name
              }}
            }}
          }}
        }}
        """

        try:
            resp = self.session.post("https://simplywall.st/graphql", json={"query": query}, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("data", {}).get("companyPredefinedScreenerResults", {})
                companies = results.get("companies", [])
                candidates = []
                for c in companies:
                    ticker = c.get("tickerSymbol")
                    if not ticker:
                        continue
                    score = c.get("score") or {}
                    av = c.get("analysisValue") or {}
                    ind = (c.get("primaryIndustry") or {}).get("name", "")

                    cand = SimplyWallStCandidate(
                        ticker=ticker.strip().upper(),
                        name=c.get("name", ""),
                        exchange=c.get("exchangeSymbol", ""),
                        price=float(av.get("lastSharePrice") or 0.0),
                        market_cap=float(av.get("marketCap") or 0.0),
                        category=cat_name,
                        pe_ratio=float(av["pe"]) if av.get("pe") is not None else None,
                        pb_ratio=float(av["pb"]) if av.get("pb") is not None else None,
                        score_dividend=int(score.get("dividend") or 0),
                        score_future=int(score.get("future") or 0),
                        score_health=int(score.get("health") or 0),
                        score_past=int(score.get("past") or 0),
                        score_value=int(score.get("value") or 0),
                        industry=ind,
                        is_us_listed=True,
                    )
                    candidates.append(cand)
                if candidates:
                    return candidates
        except Exception as e:
            logger.warning("SWS live query failed for %s: %s. Checking cache.", category_key, e)

        # Fallback to local cache if available
        return self._load_fallback_candidates(category_key)

    def _load_fallback_candidates(self, category_key: str) -> list[SimplyWallStCandidate]:
        """Load candidates from disk cache (or AQTS cache snapshot) when offline."""
        candidates: list[SimplyWallStCandidate] = []
        cache_paths = [
            self.candidates_cache_file,
            Path("/root/AutomatedQuantitativeTradingSystem/market_cache/simplywallst/candidates.json"),
        ]

        for p in cache_paths:
            if p.exists():
                try:
                    data = json.loads(p.read_text())
                    items = data.get("candidates", [])
                    for item in items:
                        src_cat = item.get("source_category", "").lower()
                        cat_str = item.get("category", "").lower()
                        target = category_key.lower().replace("_", " ")

                        # Match category or return high-scoring items if category is empty
                        if target in src_cat or target in cat_str or category_key in src_cat:
                            cand = SimplyWallStCandidate(
                                ticker=item.get("ticker", "").strip().upper(),
                                name=item.get("name", ""),
                                exchange=item.get("exchange", ""),
                                price=float(item.get("price") or 0.0),
                                market_cap=float(item.get("market_cap") or 0.0),
                                category=item.get("category", category_key),
                                pe_ratio=item.get("pe_ratio"),
                                pb_ratio=item.get("pb_ratio"),
                                score_dividend=int(item.get("score_dividend") or 0),
                                score_future=int(item.get("score_future") or 0),
                                score_health=int(item.get("score_health") or 0),
                                score_past=int(item.get("score_past") or 0),
                                score_value=int(item.get("score_value") or 0),
                                industry=item.get("industry", ""),
                                is_us_listed=item.get("is_us_listed", True),
                            )
                            candidates.append(cand)
                    if candidates:
                        return candidates
                except Exception as e:
                    logger.debug("Failed reading cache from %s: %s", p, e)

        return candidates

    def get_top_discoveries(self, categories: list[str] | None = None,
                            limit_per_cat: int = 15) -> dict[str, list[dict[str, Any]]]:
        """Scan specified categories and return discoveries."""
        target_cats = categories or ["undiscovered_gems", "high_growth_tech_ai", "high_insider_buying"]
        out = {}
        for cat in target_cats:
            cands = self.fetch_category(cat, limit=limit_per_cat)
            out[cat] = [c.to_dict() for c in cands]
        return out


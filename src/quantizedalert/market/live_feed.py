"""Unified Real-Time Market Data Feed & Rate-Limiting Daemon.

Provides low-latency market data for US & China equities:
1. Alpaca Market Data API (Batch Snapshots for up to 100 US stocks in 1 HTTP call).
2. Finnhub REST API (Single quote fallback).
3. Sina Finance Real-Time Snapshot API (Zero-auth tick stream for China A-shares).
4. Yahoo Finance Fallback (via yfinance_client).
5. RateLimitMonitor (Sliding-window token tracking, quota governance, and telemetry).
6. LivePriceDaemon (Threaded background pre-caching daemon for paper portfolio & ticker tape).
"""
from __future__ import annotations

import collections
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger("quantizedalert.market.live")


@dataclass
class LiveQuote:
    symbol: str
    price: float
    change: float | None = None
    change_pct: float | None = None
    high: float | None = None
    low: float | None = None
    open: float | None = None
    prev_close: float | None = None
    volume: float | None = None
    source: str = "unknown"
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp_iso"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(self.timestamp or time.time()))
        return d


class RateLimitMonitor:
    """Sliding-window rate limiter and quota telemetry monitor for external APIs."""

    def __init__(self, limits: dict[str, int] | None = None):
        # Default limits per 60-second window
        self.limits: dict[str, int] = limits or {
            "alpaca": 200,   # Alpaca free tier: 200 calls/min
            "finnhub": 60,   # Finnhub free tier: 60 calls/min
            "sina": 1200,    # Sina public: high capacity
            "yfinance": 120, # Yahoo: conservative rate limit
        }
        self._history: dict[str, collections.deque[float]] = {
            k: collections.deque() for k in self.limits
        }
        self._total_calls: dict[str, int] = {k: 0 for k in self.limits}
        self._total_errors: dict[str, int] = {k: 0 for k in self.limits}
        self._lock = threading.Lock()

    def _purge_old(self, provider: str, now: float) -> None:
        q = self._history.setdefault(provider, collections.deque())
        cutoff = now - 60.0
        while q and q[0] < cutoff:
            q.popleft()

    def can_request(self, provider: str) -> bool:
        """Check if provider quota has capacity in the current 60s sliding window."""
        with self._lock:
            now = time.time()
            self._purge_old(provider, now)
            q = self._history[provider]
            limit = self.limits.get(provider, 100)
            return len(q) < limit

    def record_request(self, provider: str, success: bool = True) -> None:
        """Record an API request timestamp and success/failure."""
        with self._lock:
            now = time.time()
            self._purge_old(provider, now)
            self._history.setdefault(provider, collections.deque()).append(now)
            self._total_calls[provider] = self._total_calls.get(provider, 0) + 1
            if not success:
                self._total_errors[provider] = self._total_errors.get(provider, 0) + 1

    def throttle_if_needed(self, provider: str, safety_margin: float = 0.85) -> None:
        """Sleep briefly if current usage exceeds safety margin of quota."""
        with self._lock:
            now = time.time()
            self._purge_old(provider, now)
            q = self._history.setdefault(provider, collections.deque())
            limit = self.limits.get(provider, 100)
            usage_ratio = len(q) / float(limit) if limit > 0 else 0.0

        if usage_ratio >= safety_margin:
            sleep_time = 0.2 if usage_ratio < 0.95 else 0.6
            logger.warning("Rate limit throttle active for %s: %d/%d (%.1f%%); sleeping %.2fs",
                           provider, len(q), limit, usage_ratio * 100.0, sleep_time)
            time.sleep(sleep_time)

    def get_stats(self) -> dict[str, Any]:
        """Return real-time usage telemetry across all providers."""
        with self._lock:
            now = time.time()
            stats: dict[str, Any] = {}
            for provider, limit in self.limits.items():
                self._purge_old(provider, now)
                active_calls = len(self._history.get(provider, []))
                remaining = max(0, limit - active_calls)
                status = "HEALTHY"
                if active_calls >= int(limit * 0.9):
                    status = "THROTTLED"
                elif active_calls >= int(limit * 0.75):
                    status = "WARNING"

                stats[provider] = {
                    "calls_last_minute": active_calls,
                    "limit_per_minute": limit,
                    "remaining_quota": remaining,
                    "utilization_pct": round((active_calls / limit * 100.0) if limit > 0 else 0.0, 1),
                    "total_calls": self._total_calls.get(provider, 0),
                    "total_errors": self._total_errors.get(provider, 0),
                    "status": status,
                }
            return stats


class UnifiedMarketDataFeed:
    """Multi-source live market data feeder with caching and intelligent fallback."""

    def __init__(self, cache_ttl: float = 15.0):
        self.cache_ttl = cache_ttl
        self.rate_monitor = RateLimitMonitor()
        self._cache: dict[str, tuple[LiveQuote, float]] = {}
        self._cache_lock = threading.Lock()

        # Load environment variables if not already set
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except Exception:
            pass

        # Load API keys from environment
        self.finnhub_key = os.getenv("FINNHUB_API_KEY", "").strip()
        self.alpaca_key = (
            os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY") or ""
        ).strip()
        self.alpaca_secret = (
            os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY") or ""
        ).strip()
        self.alpaca_data_url = (
            os.getenv("ALPACA_DATA_URL") or "https://data.alpaca.markets/v2"
        ).rstrip("/")

        logger.info(
            "UnifiedMarketDataFeed initialized: Finnhub=%s, Alpaca=%s, CacheTTL=%.1fs",
            "CONFIGURED" if self.finnhub_key else "MISSING",
            "CONFIGURED" if self.alpaca_key else "MISSING",
            self.cache_ttl,
        )

    def _get_from_cache(self, symbol: str) -> LiveQuote | None:
        with self._cache_lock:
            if symbol in self._cache:
                quote, ts = self._cache[symbol]
                if time.time() - ts < self.cache_ttl:
                    return quote
        return None

    def _set_cache(self, symbol: str, quote: LiveQuote) -> None:
        with self._cache_lock:
            self._cache[symbol] = (quote, time.time())

    # ---------- Alpaca Snapshots ----------
    def _fetch_alpaca_snapshots(self, symbols: list[str]) -> dict[str, LiveQuote]:
        if not self.alpaca_key or not self.alpaca_secret or not symbols:
            return {}

        self.rate_monitor.throttle_if_needed("alpaca")
        symbols_clean = [s.upper().strip() for s in symbols]
        symbols_param = ",".join(symbols_clean)
        url = f"{self.alpaca_data_url}/stocks/snapshots?symbols={urllib.parse.quote(symbols_param)}"

        req = urllib.request.Request(
            url,
            headers={
                "APCA-API-KEY-ID": self.alpaca_key,
                "APCA-API-SECRET-KEY": self.alpaca_secret,
                "User-Agent": "QuantizedAlert/2.0",
            },
        )
        quotes: dict[str, LiveQuote] = {}
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                import json
                data = json.loads(resp.read().decode("utf-8"))
                self.rate_monitor.record_request("alpaca", success=True)
                for sym, snap in data.items():
                    # Parse latest trade or quote or daily bar
                    lt = snap.get("latestTrade") or {}
                    lq = snap.get("latestQuote") or {}
                    db = snap.get("dailyBar") or {}
                    pb = snap.get("prevDailyBar") or {}

                    price = None
                    if lt.get("p"):
                        price = float(lt["p"])
                    elif lq.get("ap") and lq.get("bp") and (lq["ap"] + lq["bp"] > 0):
                        price = (float(lq["ap"]) + float(lq["bp"])) / 2.0
                    elif db.get("c"):
                        price = float(db["c"])

                    if price is None:
                        continue

                    prev_close = float(pb["c"]) if pb.get("c") else None
                    chg = round(price - prev_close, 4) if prev_close else None
                    chg_pct = round((chg / prev_close) * 100.0, 2) if prev_close and prev_close > 0 else None

                    lquote = LiveQuote(
                        symbol=sym,
                        price=round(price, 4),
                        change=chg,
                        change_pct=chg_pct,
                        high=float(db.get("h")) if db.get("h") else None,
                        low=float(db.get("l")) if db.get("l") else None,
                        open=float(db.get("o")) if db.get("o") else None,
                        prev_close=prev_close,
                        volume=float(db.get("v")) if db.get("v") else None,
                        source="alpaca_snapshot",
                        timestamp=time.time(),
                    )
                    quotes[sym] = lquote
                    self._set_cache(sym, lquote)
        except Exception as e:
            self.rate_monitor.record_request("alpaca", success=False)
            logger.warning("Alpaca snapshots fetch error for %s: %s", symbols_param, e)

        return quotes

    # ---------- Finnhub Quote ----------
    def _fetch_finnhub_quote(self, symbol: str) -> LiveQuote | None:
        if not self.finnhub_key:
            return None

        self.rate_monitor.throttle_if_needed("finnhub")
        sym_clean = symbol.upper().strip()
        url = f"https://finnhub.io/api/v1/quote?symbol={urllib.parse.quote(sym_clean)}&token={self.finnhub_key}"

        req = urllib.request.Request(url, headers={"User-Agent": "QuantizedAlert/2.0"})
        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                import json
                data = json.loads(resp.read().decode("utf-8"))
                self.rate_monitor.record_request("finnhub", success=True)
                curr = data.get("c")
                if curr and float(curr) > 0.0:
                    price = float(curr)
                    chg = float(data["d"]) if data.get("d") is not None else None
                    chg_pct = float(data["dp"]) if data.get("dp") is not None else None
                    prev_close = float(data["pc"]) if data.get("pc") else None

                    lquote = LiveQuote(
                        symbol=sym_clean,
                        price=round(price, 4),
                        change=chg,
                        change_pct=chg_pct,
                        high=float(data.get("h")) if data.get("h") else None,
                        low=float(data.get("l")) if data.get("l") else None,
                        open=float(data.get("o")) if data.get("o") else None,
                        prev_close=prev_close,
                        source="finnhub",
                        timestamp=float(data.get("t", time.time())),
                    )
                    self._set_cache(sym_clean, lquote)
                    return lquote
        except Exception as e:
            self.rate_monitor.record_request("finnhub", success=False)
            logger.warning("Finnhub quote error for %s: %s", sym_clean, e)

        return None

    # ---------- Sina Finance (China A-Shares) ----------
    def _fetch_sina_quotes(self, symbols: list[str]) -> dict[str, LiveQuote]:
        if not symbols:
            return {}

        self.rate_monitor.throttle_if_needed("sina")
        # Format symbols: SH600036 -> sh600036, SZ000001 -> sz000001
        formatted = []
        mapping = {}
        for s in symbols:
            clean = s.upper().strip()
            if clean.startswith("SH") or clean.startswith("SZ"):
                sina_sym = clean.lower()
                formatted.append(sina_sym)
                mapping[sina_sym] = clean

        if not formatted:
            return {}

        query_str = ",".join(formatted)
        url = f"http://hq.sinajs.cn/list={query_str}"
        req = urllib.request.Request(
            url,
            headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            },
        )
        quotes: dict[str, LiveQuote] = {}
        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                raw_bytes = resp.read()
                try:
                    text = raw_bytes.decode("gbk")
                except UnicodeDecodeError:
                    text = raw_bytes.decode("utf-8", errors="ignore")

                self.rate_monitor.record_request("sina", success=True)
                for line in text.splitlines():
                    if '="' not in line:
                        continue
                    header, body = line.split('="', 1)
                    sina_sym = header.split("hq_str_")[-1].strip()
                    orig_sym = mapping.get(sina_sym, sina_sym.upper())
                    payload = body.rstrip('";')
                    parts = payload.split(",")
                    if len(parts) >= 6:
                        # parts: 0=name, 1=open, 2=prev_close, 3=current_price, 4=high, 5=low
                        try:
                            price = float(parts[3])
                            prev_close = float(parts[2]) if float(parts[2]) > 0 else None
                            chg = round(price - prev_close, 4) if prev_close else None
                            chg_pct = round((chg / prev_close) * 100.0, 2) if prev_close else None

                            if price > 0:
                                lquote = LiveQuote(
                                    symbol=orig_sym,
                                    price=price,
                                    change=chg,
                                    change_pct=chg_pct,
                                    open=float(parts[1]) if float(parts[1]) > 0 else None,
                                    prev_close=prev_close,
                                    high=float(parts[4]) if float(parts[4]) > 0 else None,
                                    low=float(parts[5]) if float(parts[5]) > 0 else None,
                                    volume=float(parts[8]) if len(parts) > 8 and parts[8] else None,
                                    source="sina_live",
                                    timestamp=time.time(),
                                )
                                quotes[orig_sym] = lquote
                                self._set_cache(orig_sym, lquote)
                        except (ValueError, IndexError):
                            continue
        except Exception as e:
            self.rate_monitor.record_request("sina", success=False)
            logger.warning("Sina quote fetch error for %s: %s", query_str, e)

        return quotes

    # ---------- Public High-Level Interface ----------
    def get_quote(self, symbol: str, force_refresh: bool = False) -> LiveQuote | None:
        """Fetch a single live quote using Alpaca -> Finnhub -> Sina -> YFinance."""
        sym_clean = symbol.upper().strip()
        if not force_refresh:
            cached = self._get_from_cache(sym_clean)
            if cached is not None:
                return cached

        # Route China A-shares to Sina
        if sym_clean.startswith("SH") or sym_clean.startswith("SZ"):
            cn_res = self._fetch_sina_quotes([sym_clean])
            if sym_clean in cn_res:
                return cn_res[sym_clean]

        # Route US shares to Alpaca snapshots
        if self.alpaca_key:
            alp_res = self._fetch_alpaca_snapshots([sym_clean])
            if sym_clean in alp_res:
                return alp_res[sym_clean]

        # Fallback to Finnhub
        if self.finnhub_key:
            fin_res = self._fetch_finnhub_quote(sym_clean)
            if fin_res:
                return fin_res

        # Fallback to yfinance
        from quantizedalert.market.yfinance_client import get_current_price
        yf_price = get_current_price(sym_clean)
        if yf_price:
            lquote = LiveQuote(
                symbol=sym_clean,
                price=yf_price,
                source="yfinance_fallback",
                timestamp=time.time(),
            )
            self._set_cache(sym_clean, lquote)
            return lquote

        return None

    def get_quotes_batch(self, symbols: list[str]) -> dict[str, LiveQuote]:
        """Fetch batch quotes intelligently across providers."""
        results: dict[str, LiveQuote] = {}
        missing_us: list[str] = []
        cn_symbols: list[str] = []

        for s in symbols:
            clean = s.upper().strip()
            cached = self._get_from_cache(clean)
            if cached:
                results[clean] = cached
            elif clean.startswith("SH") or clean.startswith("SZ"):
                cn_symbols.append(clean)
            else:
                missing_us.append(clean)

        # Batch fetch China symbols
        if cn_symbols:
            results.update(self._fetch_sina_quotes(cn_symbols))

        # Batch fetch US symbols via Alpaca
        if missing_us and self.alpaca_key:
            alp_quotes = self._fetch_alpaca_snapshots(missing_us)
            results.update(alp_quotes)
            missing_us = [s for s in missing_us if s not in results]

        # Fallback for any still missing US symbols
        for sym in missing_us:
            q = self._fetch_finnhub_quote(sym)
            if q:
                results[sym] = q
            else:
                # Final fallback: yfinance
                try:
                    from quantizedalert.market.yfinance_client import get_current_price
                    p = get_current_price(sym)
                    if p:
                        lq = LiveQuote(symbol=sym, price=p, source="yfinance_fallback", timestamp=time.time())
                        results[sym] = lq
                        self._set_cache(sym, lq)
                except Exception:
                    pass

        return results

    def get_ticker_tape(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        """Return formatted items for dashboard ticker tape display."""
        default_syms = ["QQQ", "SPY", "NVDA", "AAPL", "XLE", "XLK", "ASTS", "RKLB", "LLY"]
        syms = symbols or default_syms
        quotes = self.get_quotes_batch(syms)

        items: list[dict[str, Any]] = []
        for s in syms:
            q = quotes.get(s)
            if q:
                chg_str = ""
                cls = "ticker-neu"
                if q.change_pct is not None:
                    if q.change_pct > 0:
                        chg_str = f"▲ +{q.change_pct:.2f}%"
                        cls = "ticker-up"
                    elif q.change_pct < 0:
                        chg_str = f"▼ {q.change_pct:.2f}%"
                        cls = "ticker-down"
                    else:
                        chg_str = "0.00%"

                items.append({
                    "symbol": s,
                    "price_str": f"${q.price:,.2f}",
                    "change_str": chg_str,
                    "css_class": cls,
                    "source": q.source,
                })
            else:
                items.append({
                    "symbol": s,
                    "price_str": "--",
                    "change_str": "",
                    "css_class": "ticker-neu",
                    "source": "pending",
                })
        return items


class LivePriceDaemon:
    """Background daemon periodically refreshing active portfolio and watchlist prices."""

    def __init__(self, feed: UnifiedMarketDataFeed, interval_sec: float = 15.0):
        self.feed = feed
        self.interval_sec = interval_sec
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="LivePriceDaemon", daemon=True)
            self._thread.start()
            logger.info("LivePriceDaemon started (interval=%.1fs)", self.interval_sec)

    def stop(self) -> None:
        with self._lock:
            self._running = False
            logger.info("LivePriceDaemon stopping...")

    def _loop(self) -> None:
        while self._running:
            try:
                # Gather symbols to prefetch: ticker tape + paper positions
                symbols = {"QQQ", "SPY", "NVDA", "AAPL", "XLE", "XLK", "ASTS", "RKLB", "LLY"}
                try:
                    from quantizedalert.execution.paper_engine import PaperTradingEngine
                    pe = PaperTradingEngine()
                    for t in pe.positions:
                        symbols.add(t)
                except Exception:
                    pass

                self.feed.get_quotes_batch(list(symbols))
            except Exception as e:
                logger.error("Error in LivePriceDaemon cycle: %s", e)

            # Sleep in short increments for responsive shutdown
            for _ in range(int(self.interval_sec * 10)):
                if not self._running:
                    break
                time.sleep(0.1)


# Global instances
_feed_instance: UnifiedMarketDataFeed | None = None
_daemon_instance: LivePriceDaemon | None = None
_feed_lock = threading.Lock()


def get_live_feed() -> UnifiedMarketDataFeed:
    """Singleton getter for UnifiedMarketDataFeed."""
    global _feed_instance
    with _feed_lock:
        if _feed_instance is None:
            _feed_instance = UnifiedMarketDataFeed()
        return _feed_instance


def start_price_daemon(interval_sec: float = 15.0) -> LivePriceDaemon:
    """Start the global LivePriceDaemon."""
    global _daemon_instance
    with _feed_lock:
        if _daemon_instance is None:
            feed = get_live_feed()
            _daemon_instance = LivePriceDaemon(feed, interval_sec=interval_sec)
            _daemon_instance.start()
        return _daemon_instance

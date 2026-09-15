"""Automated Conviction Breakout Telegram Dispatcher.

Monitors real-time asset prices, breakout momentum, and quantitative signals,
and dispatches institutional-grade formatted push alerts to verified user Telegram channels.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any
import requests

from quantizedalert.store import Store

logger = logging.getLogger("quantizedalert.alerts.telegram")


class TelegramDispatcher:
    """Dispatches real-time conviction alerts to Telegram users and default broadcast channels."""

    def __init__(
        self,
        bot_token: str | None = None,
        store: Store | None = None,
        default_chat_id: str | None = None,
        cooldown_sec: float = 3600.0,
    ):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("QUANTIZEDALERT_TELEGRAM_BOT_TOKEN") or ""
        self.default_chat_id = default_chat_id or os.getenv("TELEGRAM_CHAT_ID") or ""
        self.store = store
        self.cooldown_sec = cooldown_sec
        self._cooldowns: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and (self.default_chat_id or self.store))

    def send_message(self, chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
        """Send a single Telegram message via Bot API."""
        if not self.bot_token:
            logger.warning("TelegramDispatcher: bot_token not configured")
            return False
        clean_chat_id = str(chat_id).strip().lstrip("@")
        if not clean_chat_id:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": clean_chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False,
        }
        try:
            resp = requests.post(url, json=payload, timeout=8.0)
            if resp.status_code == 200 and resp.json().get("ok"):
                logger.info("Telegram alert sent to chat_id=%s", clean_chat_id)
                return True
            else:
                logger.warning("Telegram send failed (status=%s): %s", resp.status_code, resp.text)
                return False
        except Exception as e:
            logger.error("Exception sending Telegram message to %s: %s", clean_chat_id, e)
            return False

    def broadcast_message(
        self, text: str, extra_chat_ids: list[str] | None = None, parse_mode: str = "HTML"
    ) -> dict[str, bool]:
        """Broadcast message to all linked user chat IDs plus default channel."""
        targets: set[str] = set()
        if self.default_chat_id:
            targets.add(self.default_chat_id.strip())
        if self.store:
            try:
                for cid in self.store.get_all_telegram_chat_ids():
                    targets.add(cid.strip())
            except Exception as e:
                logger.warning("Failed reading store telegram chat IDs: %s", e)
        if extra_chat_ids:
            for ec in extra_chat_ids:
                if ec:
                    targets.add(str(ec).strip())

        results = {}
        for cid in targets:
            results[cid] = self.send_message(cid, text, parse_mode=parse_mode)
        return results

    def dispatch_breakout_alert(
        self,
        ticker: str,
        price: float,
        change_pct: float,
        conviction_score: float,
        catalyst: str = "",
        target_price: float | None = None,
        stop_loss: float | None = None,
        reason: str = "",
        force: bool = False,
    ) -> dict[str, bool]:
        """Dispatch high-conviction breakout alert if not in cooldown."""
        t_clean = ticker.upper().strip()
        key = f"{t_clean}:breakout"
        now = time.time()

        with self._lock:
            if not force and key in self._cooldowns:
                if now - self._cooldowns[key] < self.cooldown_sec:
                    logger.debug("Skipping alert for %s, active cooldown", key)
                    return {}
            self._cooldowns[key] = now

        target_str = f"${target_price:.2f}" if target_price else "Open Target (10x Horizon)"
        stop_str = f"${stop_loss:.2f}" if stop_loss else "Trailing 8% ATR"
        arrow = "🟢 ▲" if change_pct >= 0 else "🔴 ▼"

        msg = (
            f"💎 <b>QUANTIZEDALERT • CONVICTION BREAKOUT</b>\n\n"
            f"📈 <b>Asset:</b> <code>${t_clean}</code>\n"
            f"⚡ <b>Live Price:</b> <b>${price:.2f}</b> ({arrow} {change_pct:+.2f}%)\n"
            f"🎯 <b>Conviction Score:</b> <b>{conviction_score:.1f}/100</b>\n"
        )
        if catalyst:
            msg += f"🔥 <b>Catalyst:</b> {catalyst}\n"
        msg += (
            f"🎯 <b>Price Target:</b> {target_str}\n"
            f"🛡️ <b>Risk Stop:</b> {stop_str}\n"
        )
        if reason:
            msg += f"💡 <b>Setup:</b> {reason}\n"

        msg += (
            f"\n📊 <i>System Source: QuantizedAlert Autonomous Qlib ML Engine</i>\n"
            f"🔗 <a href=\"https://quant.eliginetwork.org/w/alpha_gems\">Open Institutional Terminal →</a>"
        )

        return self.broadcast_message(msg)


_dispatcher_instance: TelegramDispatcher | None = None
_dispatcher_lock = threading.Lock()


def get_telegram_dispatcher(store: Store | None = None) -> TelegramDispatcher:
    global _dispatcher_instance
    with _dispatcher_lock:
        if _dispatcher_instance is None:
            _dispatcher_instance = TelegramDispatcher(store=store)
        elif store is not None and _dispatcher_instance.store is None:
            _dispatcher_instance.store = store
        return _dispatcher_instance

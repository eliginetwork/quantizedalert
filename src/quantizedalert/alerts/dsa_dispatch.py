"""Layer G delivery adapter — daily_stock_analysis notification engine.

DSA is used, not reimplemented: its `NotificationService` (a mixin of the 14
channel senders in `src/notification_sender/`) does the actual HTTP/SMTP
delivery, chunking, image fallback, and per-channel diagnostics. QuantizedAlert's
contribution is *what* to send (alert intelligence) and *for whom* (per
workspace routing); everything about *how messages reach channels* is DSA's.

Amendment E: every dispatch reports `engine_source`. If the asset fails, the
call raises `AlertDeliveryError` — no silent fallback to a hand-rolled sender.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from quantizedalert.assets.dsa_path import dsa_importable, dsa_module

logger = logging.getLogger("quantizedalert.dsa")

# channel slug -> DSA sender method
CHANNEL_METHODS = {
    "telegram": "send_to_telegram",
    "slack": "send_to_slack",
    "discord": "send_to_discord",
    "email": "send_to_email",
    "feishu": "send_to_feishu",
    "wecom": "send_to_wechat",
    "dingtalk": "send_to_dingtalk",
    "pushover": "send_to_pushover",
    "ntfy": "send_to_ntfy",
    "gotify": "send_to_gotify",
    "pushplus": "send_to_pushplus",
    "serverchan3": "send_to_serverchan3",
    "astrbot": "send_to_astrbot",
    "custom_webhook": "send_to_custom",
}


class AlertDeliveryError(RuntimeError):
    pass


class DispatchSink:
    """Test/dev recording sink: monkey-patched over DSA sender methods.

    Only ever installed via `DSAlerter(dry_run=True)` — dry_run records what
    *would* be delivered through the real DSA contract and is observable in the
    decision payload, never presented as a real delivery.
    """

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def __call__(self, content: str, **kw: Any) -> bool:
        self.sent.append({"content": content, **kw})
        return True


@dataclass
class DSAlerter:
    dsa_path: str
    dry_run: bool = False
    _service: Any = None
    _sink: DispatchSink | None = None

    def __post_init__(self) -> None:
        # DSA's Config.get_instance() reads env at construction time; channels are
        # configured through the standard DSA env contract (TELEGRAM_BOT_TOKEN, ...).
        with dsa_importable(self.dsa_path):
            notification = dsa_module("src.notification", self.dsa_path)
            config_mod = dsa_module("src.config", self.dsa_path)
            self._config = config_mod.get_config()
            self._service = notification.NotificationService()
        if self.dry_run:
            self._sink = DispatchSink()
            for m in CHANNEL_METHODS.values():
                setattr(self._service, m, self._sink)
        self.engine_source = "daily_stock_analysis"

    # ---------- introspection ----------
    @property
    def service(self) -> Any:
        return self._service

    def configured_channels(self) -> list[str]:
        with dsa_importable(self.dsa_path):
            notification = dsa_module("src.notification", self.dsa_path)
            chs = notification.NotificationService.detect_configured_channels(self._config)
        names = []
        for ch in chs:
            names.append(str(getattr(ch, "value", ch)))
        return names

    # ---------- delivery ----------
    def dispatch(self, content_md: str, channels: list[str],
                 severity: str | None = None,
                 dedup_key: str | None = None,
                 cooldown_key: str | None = None,
                 route_type: str | None = None) -> dict[str, bool]:
        """Deliver markdown to selected channels through DSA senders.

        Returns {channel: delivered_bool}. Raises AlertDeliveryError if the
        DSA service itself is unavailable (integration broken → fail loudly).
        """
        if self._service is None:
            raise AlertDeliveryError("DSA NotificationService unavailable")
        results: dict[str, bool] = {}
        for slug in channels:
            meth = CHANNEL_METHODS.get(slug)
            if meth is None:
                results[slug] = False
                logger.warning("unknown alert channel %s (not a DSA sender)", slug)
                continue
            fn = None
            try:
                fn = getattr(self._service, meth)
            except AttributeError:
                pass
            if fn is None:
                raise AlertDeliveryError(
                    f"DSA service missing sender method {meth}; asset integration broken")
            try:
                ok = bool(fn(content_md))
            except AlertDeliveryError:
                raise
            except Exception as e:
                logger.error("DSA send failed on %s: %s", slug, e)
                ok = False
            results[slug] = ok
        if self._sink is not None:
            logger.info("dry-run dispatch recorded %d DSA sends", len(self._sink.sent))
            # Amendment E: dry-run sends must be identifiable in the audit trail.
            results["_dry_run"] = True
        return results

    def send(self, content_md: str, severity: str | None = None,
             dedup_key: str | None = None) -> bool:
        """All-configured-channels path using DSA's unified `send()` contract
        (routing/severity/dedup are DSA-native parameters)."""
        with dsa_importable(self.dsa_path):
            try:
                return bool(self._service.send(content_md, severity=severity,
                                               dedup_key=dedup_key))
            except TypeError:
                return bool(self._service.send(content_md))

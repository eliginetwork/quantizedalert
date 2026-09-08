"""Layer E — deployment: schedule validated models for recurring daily runs.

APScheduler (Class 4 tooling) replaces DSA's single-slot scheduler — deviation
documented in DEVIATIONS.md §2. Each enabled deployment becomes a daily cron job
running DailyPipeline.run for its workspace.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from unlockaid.config import WorkspaceConfig
from unlockaid.store import Store

logger = logging.getLogger("unlockaid.deploy")


class DeployScheduler:
    def __init__(self, store: Store, run_fn: Callable[[WorkspaceConfig], object],
                 config_loader: Callable[[str], WorkspaceConfig]):
        self.store = store
        self.run_fn = run_fn
        self.config_loader = config_loader
        self.scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    def _job(self, workspace_id: str) -> None:
        try:
            cfg = self.config_loader(workspace_id)
            res = self.run_fn(cfg)
            logger.info("scheduled run %s ok=%s", workspace_id, getattr(res, "ok", None))
        except Exception:
            logger.exception("scheduled run failed for %s", workspace_id)

    def sync(self) -> list[str]:
        """Register one cron job per enabled deployment; returns job list."""
        deps = self.store.list_deployments()
        job_ids = []
        for d in deps:
            hh, mm = (d["schedule_time"] or "17:30").split(":")
            jid = f"daily:{d['workspace_id']}"
            self.scheduler.add_job(
                self._job, CronTrigger(hour=int(hh), minute=int(mm)),
                args=[d["workspace_id"]], id=jid, replace_existing=True,
                misfire_grace_time=3600)
            job_ids.append(jid)
        return job_ids

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("deploy scheduler started with jobs=%s",
                        [j.id for j in self.scheduler.get_jobs()])

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

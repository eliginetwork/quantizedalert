"""SQLite persistence: model registry (Layer D), prediction history (F),
alert log + engagement (G), usage metering (commercial), jobs (E), scorecard (§23).

Single-file DB keeps the database line of unit economics (§22) near zero.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS models (
  model_id TEXT PRIMARY KEY, name TEXT, version TEXT, status TEXT,
  dataset_ref TEXT, factor_set TEXT, hyperparameters TEXT,
  experiment_ref TEXT, artifact_path TEXT, validation TEXT,
  workspace_id TEXT, created_at TEXT, created_by TEXT, engine_source TEXT
);
CREATE TABLE IF NOT EXISTS predictions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT, model_id TEXT, instrument TEXT, asof TEXT,
  score REAL, "rank" INTEGER,
  UNIQUE(workspace_id, model_id, instrument, asof)
);
CREATE INDEX IF NOT EXISTS ix_pred_ws_date ON predictions(workspace_id, asof);
CREATE TABLE IF NOT EXISTS alerts (
  event_id TEXT PRIMARY KEY, workspace_id TEXT, kind TEXT, title TEXT,
  severity TEXT, score REAL, components TEXT, instruments TEXT, models TEXT,
  deliver INTEGER, suppress_reason TEXT, channels TEXT, delivered TEXT,
  created_at TEXT, asof TEXT, dedup_key TEXT,
  viewed_at TEXT, clicked_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_alert_ws_date ON alerts(workspace_id, asof);
CREATE TABLE IF NOT EXISTS daily_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT, asof TEXT, ok INTEGER,
  model_id TEXT, error TEXT, payload TEXT, started_at TEXT, finished_at TEXT,
  UNIQUE(workspace_id, asof)
);
CREATE TABLE IF NOT EXISTS deployments (
  workspace_id TEXT PRIMARY KEY, model_id TEXT, enabled INTEGER,
  schedule_time TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY, workspace_id TEXT, kind TEXT, status TEXT,
  started_at TEXT, finished_at TEXT, result TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT, metric TEXT,
  qty REAL, date TEXT, ref TEXT
);
CREATE INDEX IF NOT EXISTS ix_usage_ws_date ON usage(workspace_id, date, metric);
CREATE TABLE IF NOT EXISTS customers (
  workspace_id TEXT PRIMARY KEY, email TEXT, plan TEXT,
  stripe_customer_id TEXT, stripe_subscription_id TEXT, status TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS data_health (
  id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT, asof TEXT,
  status TEXT, detail TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS drift (
  id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT, model_id TEXT, asof TEXT,
  metric TEXT, value REAL, baseline REAL, detail TEXT, created_at TEXT
);
"""


def utcnow() -> str:
    # NOTE: kept in SQLite's native datetime text format ("YYYY-MM-DD HH:MM:SS",
    # UTC) so string comparisons against datetime('now', ...) in queries are
    # exact, not lexicographic-by-luck.
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---------- model registry (Layer D) ----------
    def put_model(self, rec: dict[str, Any]) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO models VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec["model_id"], rec["name"], rec["version"], rec["status"],
                 rec["dataset_ref"], rec["factor_set"],
                 json.dumps(rec["hyperparameters"]), rec.get("experiment_ref"),
                 rec.get("artifact_path"),
                 json.dumps(rec.get("validation")) if rec.get("validation") else None,
                 rec.get("workspace_id"), rec.get("created_at", utcnow()),
                 rec.get("created_by", "research-agent"),
                 rec.get("engine_source", "qlib")))

    @staticmethod
    def _model_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["hyperparameters"] = json.loads(d["hyperparameters"] or "{}")
        d["validation"] = json.loads(d["validation"]) if d["validation"] else None
        return d

    def get_model(self, model_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM models WHERE model_id=?", (model_id,)).fetchone()
        return self._model_row(r) if r else None

    def list_models(self, workspace_id: str | None = None,
                    status: str | None = None) -> list[dict]:
        conds, args = [], []
        if workspace_id:
            conds.append("workspace_id=?"); args.append(workspace_id)
        if status:
            conds.append("status=?"); args.append(status)
        q = "SELECT * FROM models"
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY created_at DESC"
        with self._conn() as c:
            return [self._model_row(r) for r in c.execute(q, args)]

    # ---------- predictions ----------
    def put_predictions(self, preds: list[dict]) -> None:
        with self._conn() as c:
            c.executemany(
                'INSERT OR REPLACE INTO predictions'
                ' (workspace_id,model_id,instrument,asof,score,"rank")'
                ' VALUES (:workspace_id,:model_id,:instrument,:asof,:score,:rank)', preds)

    def get_predictions(self, workspace_id: str, asof: str) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                'SELECT * FROM predictions WHERE workspace_id=? AND asof=?'
                ' ORDER BY "rank"', (workspace_id, asof))]

    def get_previous_predictions(self, workspace_id: str, model_id: str,
                                 before: str) -> list[dict]:
        """Latest prediction batch strictly before `before` (for rank-change deltas)."""
        with self._conn() as c:
            row = c.execute(
                "SELECT MAX(asof) a FROM predictions WHERE workspace_id=? AND model_id=?"
                " AND asof<?", (workspace_id, model_id, before)).fetchone()
            if not row or not row["a"]:
                return []
            rows = c.execute(
                'SELECT * FROM predictions WHERE workspace_id=? AND model_id=? AND asof=?'
                ' ORDER BY "rank"', (workspace_id, model_id, row["a"])).fetchall()
        return [dict(r) for r in rows]

    # ---------- deployments (Layer E) ----------
    def set_deployment(self, workspace_id: str, model_id: str, enabled: bool,
                       schedule_time: str) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO deployments VALUES (?,?,?,?,?)",
                      (workspace_id, model_id, int(enabled), schedule_time, utcnow()))

    def get_deployment(self, workspace_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM deployments WHERE workspace_id=?",
                          (workspace_id,)).fetchone()
        return dict(r) if r else None

    def list_deployments(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM deployments WHERE enabled=1")]

    # ---------- daily runs / jobs ----------
    def put_daily_run(self, workspace_id: str, asof: str, ok: bool, model_id: str,
                      error: str | None, payload: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO daily_runs"
                " (workspace_id,asof,ok,model_id,error,payload,started_at,finished_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (workspace_id, asof, int(ok), model_id, error,
                 json.dumps(payload), utcnow(), utcnow()))

    def latest_daily_run(self, workspace_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM daily_runs WHERE workspace_id=?"
                          " ORDER BY asof DESC LIMIT 1", (workspace_id,)).fetchone()
        return dict(r) if r else None

    def recent_daily_runs(self, workspace_id: str, limit: int = 10) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT asof, ok, payload FROM daily_runs WHERE workspace_id=?"
                " ORDER BY asof DESC LIMIT ?", (workspace_id, limit)).fetchall()
        out = []
        for r in rows:
            pl = json.loads(r["payload"]) if r["payload"] else {}
            out.append({"asof": r["asof"], "ok": bool(r["ok"]),
                        "n_pred": pl.get("n_predictions", 0),
                        "n_alerts": sum(1 for a in pl.get("alerts", [])
                                        if isinstance(a, dict) and a.get("deliver"))})
        return out

    def put_job(self, job_id: str, workspace_id: str, kind: str, status: str,
                result: dict | None = None, error: str | None = None) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?,?)",
                      (job_id, workspace_id, kind, status, utcnow(), utcnow(),
                       json.dumps(result) if result else None, error))

    def job_stats(self) -> dict:
        with self._conn() as c:
            rows = c.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    # ---------- alerts (Layer G audit) ----------
    def record_alert(self, a: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO alerts"
                " (event_id,workspace_id,kind,title,severity,score,components,"
                " instruments,models,deliver,suppress_reason,channels,delivered,"
                " created_at,asof,dedup_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (a["event_id"], a["workspace_id"], a["kind"], a["title"], a["severity"],
                 a["score"], json.dumps(a.get("components", {})),
                 json.dumps(a.get("instruments", [])), json.dumps(a.get("models", [])),
                 int(a["deliver"]), a.get("suppress_reason"),
                 json.dumps(a.get("channels", [])), json.dumps(a.get("delivered", {})),
                 a.get("created_at", utcnow()), a.get("asof"), a.get("dedup_key")))

    def recent_alerts(self, workspace_id: str, since_hours: int = 24) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM alerts WHERE workspace_id=? AND created_at >"
                " datetime('now', ?) ORDER BY created_at DESC",
                (workspace_id, f"-{since_hours} hours")).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for col in ("components", "instruments", "models", "channels",
                        "delivered"):
                default = "{}" if col in ("components", "delivered") else "[]"
                d[col] = json.loads(d[col] or default)
            d["deliver"] = bool(d["deliver"])
            out.append(d)
        return out

    def alert_dedup_exists(self, workspace_id: str, dedup_key: str,
                           since_hours: int) -> bool:
        if not dedup_key:
            return False
        with self._conn() as c:
            r = c.execute(
                "SELECT 1 FROM alerts WHERE workspace_id=? AND dedup_key=?"
                " AND deliver=1 AND created_at > datetime('now', ?) LIMIT 1",
                (workspace_id, dedup_key, f"-{since_hours} hours")).fetchone()
        return r is not None

    def mark_alert_viewed(self, event_id: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE alerts SET viewed_at=? WHERE event_id=?",
                      (utcnow(), event_id))

    # ---------- usage metering ----------
    def meter(self, workspace_id: str, metric: str, qty: float = 1,
              ref: str = "") -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        with self._conn() as c:
            c.execute("INSERT INTO usage (workspace_id,metric,qty,date,ref) VALUES (?,?,?,?,?)",
                      (workspace_id, metric, qty, today, ref))

    def usage_total(self, workspace_id: str, metric: str, since_date: str) -> float:
        with self._conn() as c:
            r = c.execute(
                "SELECT COALESCE(SUM(qty),0) t FROM usage WHERE workspace_id=?"
                " AND metric=? AND date>=?", (workspace_id, metric, since_date)).fetchone()
        return float(r["t"])

    def usage_by_day(self, workspace_id: str, metric: str, date: str) -> float:
        with self._conn() as c:
            r = c.execute(
                "SELECT COALESCE(SUM(qty),0) t FROM usage WHERE workspace_id=?"
                " AND metric=? AND date=?", (workspace_id, metric, date)).fetchone()
        return float(r["t"])

    # ---------- customers ----------
    def put_customer(self, workspace_id: str, email: str, plan: str,
                     stripe_customer_id: str | None = None,
                     stripe_subscription_id: str | None = None) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO customers (workspace_id,email,plan,"
                "stripe_customer_id,stripe_subscription_id,status,created_at)"
                " VALUES (?,?,?,?,?,?,COALESCE("
                "(SELECT created_at FROM customers WHERE workspace_id=?),?))",
                (workspace_id, email, plan, stripe_customer_id, stripe_subscription_id,
                 "active", workspace_id, utcnow()))

    def get_customer(self, workspace_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM customers WHERE workspace_id=?",
                          (workspace_id,)).fetchone()
        return dict(r) if r else None

    def set_customer_plan(self, workspace_id: str, plan: str,
                          stripe_subscription_id: str | None = None) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE customers SET plan=?,"
                " stripe_subscription_id=COALESCE(?, stripe_subscription_id)"
                " WHERE workspace_id=?", (plan, stripe_subscription_id, workspace_id))

    def list_customers(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM customers")]

    # ---------- data health / drift ----------
    def put_data_health(self, workspace_id: str, asof: str, status: str,
                        detail: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO data_health (workspace_id,asof,status,detail,created_at)"
                " VALUES (?,?,?,?,?)", (workspace_id, asof, status, json.dumps(detail),
                                        utcnow()))

    def put_drift(self, workspace_id: str, model_id: str, asof: str, metric: str,
                  value: float, baseline: float, detail: dict | None = None) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO drift"
                " (workspace_id,model_id,asof,metric,value,baseline,detail,created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (workspace_id, model_id, asof, metric, value, baseline,
                 json.dumps(detail or {}), utcnow()))

    def drift_history(self, workspace_id: str, model_id: str, metric: str,
                      limit: int = 60) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM drift WHERE workspace_id=? AND model_id=? AND metric=?"
                " ORDER BY asof DESC LIMIT ?",
                (workspace_id, model_id, metric, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ---------- scorecard (§23) ----------
    def scorecard(self, workspace_id: str) -> dict:
        with self._conn() as c:
            runs = c.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(ok),0) s FROM daily_runs"
                " WHERE workspace_id=?", (workspace_id,)).fetchone()
            alerts = c.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(deliver),0) d FROM alerts"
                " WHERE workspace_id=?", (workspace_id,)).fetchone()
            viewed = c.execute(
                "SELECT COUNT(*) n FROM alerts WHERE workspace_id=?"
                " AND viewed_at IS NOT NULL AND deliver=1", (workspace_id,)).fetchone()
            deployed = c.execute(
                "SELECT COUNT(*) n FROM deployments WHERE workspace_id=? AND enabled=1",
                (workspace_id,)).fetchone()
        return {
            "workspace_id": workspace_id,
            "daily_runs": runs["n"], "daily_runs_ok": runs["s"],
            "alerts_generated": alerts["n"], "alerts_delivered": alerts["d"],
            "alerts_viewed": viewed["n"],
            "job_stats": self.job_stats(),
            "deployed_models": deployed["n"],
        }

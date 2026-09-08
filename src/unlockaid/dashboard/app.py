"""Layer H — dashboard: What changed → Which assets/models → How significant →
Historical context. Served by FastAPI (the runnable product interface, Amendment I).
"""
from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from unlockaid.config import PlatformConfig, WorkspaceConfig
from unlockaid.store import Store

_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>UnlockAid — {{ name }}</title>
<style>
:root{--bg:#0b0e14;--panel:#141a26;--ink:#e6edf3;--dim:#8b98a9;--gold:#d4a94e;--red:#e5534b;--green:#57ab5a;--blue:#4c8fd6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif}
header{padding:18px 28px;border-bottom:1px solid #1f2733;display:flex;justify-content:space-between;align-items:center}
h1{font-size:18px;margin:0}h1 b{color:var(--gold)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;padding:20px 28px}
.card{background:var(--panel);border:1px solid #1f2733;border-radius:10px;padding:14px 16px}
.card h3{margin:0 0 8px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}
.big{font-size:22px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--dim);font-weight:500;text-align:left;padding:6px 8px;border-bottom:1px solid #1f2733}
td{padding:6px 8px;border-bottom:1px solid #171e29}
.pos{color:var(--green)}.neg{color:var(--red)}.neu{color:var(--dim)}
.chip{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;border:1px solid}
.crit{color:var(--red);border-color:var(--red)}.high{color:#f0883e;border-color:#f0883e}
.med{color:var(--gold);border-color:var(--gold)}.low{color:var(--dim);border-color:var(--dim)}
section{padding:6px 28px 22px}section h2{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:var(--dim)}
.bar{height:6px;background:#1f2733;border-radius:3px;position:relative;margin-top:4px}
.bar i{position:absolute;left:0;top:0;bottom:0;background:var(--blue);border-radius:3px}
footer{padding:14px 28px;color:var(--dim);font-size:12px;border-top:1px solid #1f2733}
</style></head><body>
<header><h1>🔓 <b>UnlockAid</b> — {{ name }}</h1>
<span class="chip {{ status_cls }}">{{ status_text }}</span></header>
<div class="grid">
<div class="card"><h3>As-of</h3><div class="big">{{ asof }}</div><div class="neu">{{ n_pred }} instruments scored</div></div>
<div class="card"><h3>Model</h3><div class="big">{{ model_id }}</div><div class="neu">{{ model_desc }}</div></div>
<div class="card"><h3>Alerts today</h3><div class="big">{{ n_delivered }} / {{ n_events }}</div><div class="neu">budget {{ max_alerts }}/day · {{ n_suppressed }} suppressed</div></div>
<div class="card"><h3>Data health</h3><div class="big">{{ health }}</div><div class="neu">stale {{ stale }} · anomaly {{ anomaly }} · missing {{ missing }}</div></div>
</div>
<section><h2>What changed — watchlist &amp; portfolio</h2>
<table><tr><th>Asset</th><th>Rank</th><th>Δ</th><th>Score</th><th>Price</th><th>1d</th></tr>
{% for c in changes %}<tr><td>{{ c.instrument }}</td><td>{{ c.rank }}</td>
<td class="{{ 'pos' if c.delta and c.delta>0 else ('neg' if c.delta and c.delta<0 else 'neu') }}">{{ c.delta_s }}</td>
<td>{{ c.score }}</td><td>{{ c.price }}</td><td class="{{ 'pos' if c.chg and c.chg>0 else 'neg' if c.chg and c.chg<0 else 'neu' }}">{{ c.chg_s }}</td></tr>
{% endfor %}</table></section>
<section><h2>Alert stream (today, ranked by value)</h2>
{% for a in alerts %}<div class="card" style="margin-bottom:8px">
<span class="chip {{ a.sev_cls }}">{{ a.severity }}</span> <b>{{ a.title }}</b>
<span class="neu">— value {{ a.score }} · {{ a.kind }} · {{ a.state }}</span>
{% if a.instruments %}<div class="neu">assets: {{ a.instruments }}</div>{% endif %}
{% if a.models %}<div class="neu">models: {{ a.models }}</div>{% endif %}
<div class="bar" title="severity/relevance/confidence"><i style="width:{{ a.score_pct }}%"></i></div>
</div>{% else %}<div class="neu">No events today — quiet is a feature.</div>{% endfor %}
</section>
<section><h2>Historical context — recent daily runs</h2>
<table><tr><th>Date</th><th>OK</th><th>Predictions</th><th>Delivered alerts</th></tr>
{% for r in history %}<tr><td>{{ r.asof }}</td><td class="{{ 'pos' if r.ok else 'neg' }}">{{ '✓' if r.ok else '✗' }}</td><td>{{ r.n_pred }}</td><td>{{ r.n_alerts }}</td></tr>{% endfor %}</table></section>
<section><h2>Portfolio intelligence</h2><div class="card">{{ portfolio }}</div></section>
<footer>UnlockAid — research → backtest → validate → deploy → monitor → alert ·
data: qlib {{ engine_qlib }} · delivery: daily_stock_analysis {{ engine_dsa }}</footer>
</body></html>"""


def build_app(platform_cfg: PlatformConfig, store: Optional[Store] = None) -> FastAPI:
    app = FastAPI(title="UnlockAid")
    from jinja2 import Template
    tpl = Template(_TEMPLATE)
    store = store or Store(platform_cfg.db_path)

    def workspace_ids() -> list[str]:
        p = platform_cfg.workspace_dir
        return sorted(f[:-5] for f in os.listdir(p) if f.endswith(".yaml")) if os.path.isdir(p) else []

    def render(ws: str) -> str:
        try:
            wc = WorkspaceConfig.load(os.path.join(p := platform_cfg.workspace_dir,
                                                   f"{ws}.yaml"))
        except (FileNotFoundError, NotADirectoryError):
            wc = None
        run = store.latest_daily_run(ws)
        if run and run["payload"]:
            payload = json.loads(run["payload"]) if isinstance(run["payload"], str) else run["payload"]
        else:
            payload = None
        alerts = store.recent_alerts(ws, since_hours=48)
        cust = store.get_customer(ws) or {}
        plan = wc.plan if wc else (cust.get("plan", "free"))

        sev_cls = {"critical": "crit", "high": "high", "medium": "med", "low": "low", "info": "low"}
        alert_rows = []
        for a in sorted(alerts, key=lambda x: -(x["score"] or 0)):
            alert_rows.append({
                "title": a["title"], "kind": a["kind"], "severity": a["severity"],
                "sev_cls": sev_cls.get(a["severity"], "low"),
                "score": f"{(a['score'] or 0):.2f}",
                "score_pct": int((a["score"] or 0) * 100),
                "state": "delivered" if a["deliver"] else f"suppressed ({a['suppress_reason']})",
                "instruments": ", ".join(a["instruments"][:4]),
                "models": ", ".join(a["models"][:2])})
        changes = []
        history = []
        portfolio = "no portfolio configured"
        n_pred = n_delivered = n_events = n_suppressed = stale = anomaly = missing = 0
        asof = health = "—"
        n_events = len(alerts)
        n_delivered = sum(1 for a in alerts if a["deliver"])
        n_suppressed = n_events - n_delivered
        if payload:
            asof = payload.get("asof", "")
            n_pred = payload.get("n_predictions", 0)
            for c in payload.get("changes", [])[:12]:
                d = c.get("rank_delta")
                chg = c.get("price_change_pct")
                changes.append({"instrument": c["instrument"], "rank": c["rank"],
                                "delta": d, "delta_s": f"{d:+d}" if d is not None else "new",
                                "score": f"{c['score']:.4f}",
                                "price": f"{c['price']:.2f}" if c.get("price") else "—",
                                "chg": chg,
                                "chg_s": f"{chg:+.2%}" if chg is not None else "—"})
            dh = payload.get("data_health") or {}
            if dh:
                health = "OK" if dh.get("fresh") and not dh.get("anomaly_count") else "ATTENTION"
                stale = sum(1 for a in dh.get("assets", []) if a["status"] == "stale")
                anomaly = dh.get("anomaly_count", 0)
                missing = dh.get("status") and sum(
                    1 for a in dh.get("assets", []) if a["status"] == "missing")
            pfo = payload.get("portfolio") or {}
            if pfo:
                portfolio = (f"scored: {pfo.get('n_scored')} · "
                             f"concentration(HHI): {pfo.get('concentration') if pfo.get('concentration') is not None else 'n/a (watchlist mode)'} · "
                             f"model-weighted score: {pfo.get('weighted_model_score') if pfo.get('weighted_model_score') is not None else 'n/a'} · "
                             f"top picks: {', '.join(t['instrument'] for t in (pfo.get('top10') or [])[:5])}")
            # per-day history
            import sqlite3
            with store._conn() as c:
                rows = c.execute(
                    "SELECT asof, ok, payload FROM daily_runs WHERE workspace_id=?"
                    " ORDER BY asof DESC LIMIT 10", (ws,)).fetchall()
            for r in rows:
                pl = json.loads(r["payload"]) if r["payload"] else {}
                history.append({"asof": r["asof"], "ok": bool(r["ok"]),
                                "n_pred": pl.get("n_predictions", 0),
                                "n_alerts": sum(1 for a in pl.get("alerts", []) if a.get("deliver"))})
        model_desc = ""
        model_id = run["model_id"] if run else "not deployed"
        if run:
            m = store.get_model(run["model_id"])
            if m:
                model_desc = f"{m['name']} v{m['version']} · {m['status']}"
        return tpl.render(name=ws, plan=plan, asof=asof or "—", model_id=model_id,
                          model_desc=model_desc or "—", n_pred=n_pred,
                          n_delivered=n_delivered, n_events=n_events,
                          n_suppressed=n_suppressed,
                          max_alerts=(wc.alerts.max_alerts_per_day if wc else 5),
                          health=health, stale=stale, anomaly=anomaly, missing=missing,
                          changes=changes, alerts=alert_rows, history=history,
                          portfolio=portfolio, status_cls="low" if run and run["ok"] else "crit",
                          status_text=f"plan: {plan}",
                          engine_qlib="0.9.x", engine_dsa="enabled")

    @app.get("/", response_class=HTMLResponse)
    def index():
        ws = workspace_ids()
        rows = "".join(
            f"<li style='margin:6px 0'><a style='color:#4c8fd6' href='/w/{w}'>{w}</a></li>"
            for w in ws)
        return (f"<html><body style='background:#0b0e14;color:#e6edf3;font-family:sans-serif;"
                f"padding:40px'><h1>🔓 UnlockAid</h1><p>Workspaces:</p><ul>{rows or '<li>none yet</li>'}</ul>"
                f"<p style='color:#8b98a9'>REST: /api/&lt;ws&gt;/summary · /api/&lt;ws&gt;/alerts · /api/&lt;ws&gt;/predictions?asof=</p></body></html>")

    @app.get("/w/{ws}", response_class=HTMLResponse)
    def workspace_page(ws: str):
        return render(ws)

    @app.get("/api/{ws}/summary")
    def summary(ws: str):
        run = store.latest_daily_run(ws)
        if not run:
            raise HTTPException(404, "no runs for workspace")
        return json.loads(run["payload"])

    @app.get("/api/{ws}/alerts")
    def alerts(ws: str):
        return store.recent_alerts(ws, since_hours=72)

    @app.get("/api/{ws}/predictions")
    def predictions(ws: str, asof: str = ""):
        if not asof:
            run = store.latest_daily_run(ws)
            if not run:
                raise HTTPException(404, "no runs")
            asof = run["asof"]
        return store.get_predictions(ws, asof)

    @app.get("/api/{ws}/scorecard")
    def scorecard(ws: str):
        return store.scorecard(ws)

    @app.post("/api/{ws}/alerts/{event_id}/view")
    def mark_viewed(ws: str, event_id: str):
        store.mark_alert_viewed(event_id)
        return {"ok": True}

    return app

"""UnlockAid front-door CLI.

Every subcommand executes the real pipeline (qlib asset + DSA asset). No stubs,
no "coming soon" (Playbook Amendment I). Wire layout:

  unlockaid data refresh|health      Layer A
  unlockaid research <ws>            Layer B (train + backtest via qlib)
  unlockaid validate <ws> <model>    Layer C (gates + walk-forward + overfit audit)
  unlockaid deploy <ws> <model>      Layers D+E (registry + schedule)
  unlockaid daily <ws>               Layers F+G (analysis + alert dispatch)
  unlockaid alert-test <ws>          Layer G delivery proof (real DSA senders)
  unlockaid dashboard|serve          Layer H
  unlockaid discover|experiments|explain   §6 agents (qlib-backed)
  unlockaid scorecard|economics      §22/§23
  unlockaid e2e                      full MVP loop, on demand
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from unlockaid import __version__
from unlockaid.config import AlertPrefs, PlatformConfig, WorkspaceConfig
from unlockaid.engine.qlib_engine import QlibEngine
from unlockaid.store import Store

logger = logging.getLogger("unlockaid.cli")


def _configure_logging() -> None:
    level = os.environ.get("UNLOCKAID_LOG", "INFO").upper()
    logging.basicConfig(level=level,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s",
                        force=True)
    logger.setLevel(level)


def _ctx():
    pcfg = PlatformConfig.load()
    store = Store(pcfg.db_path)
    engine = QlibEngine(provider_uri=os.path.expanduser(pcfg.qlib_provider_uri), region="cn")
    return pcfg, store, engine


def _load_ws(pcfg: PlatformConfig, ws: str) -> WorkspaceConfig:
    p = Path(pcfg.workspace_dir) / f"{ws}.yaml"
    if not p.exists():
        p2 = Path(pcfg.workspace_dir) / f"{ws}.yaml.example"
        if p2.exists():
            p = p2
        else:
            sys.exit(f"workspace '{ws}' not found: {p} (create with `unlockaid init-workspace`)")
    return WorkspaceConfig.load(p)


def _alerter(pcfg: PlatformConfig):
    from unlockaid.alerts.dsa_dispatch import DSAlerter
    dry = os.environ.get("UNLOCKAID_DRY_RUN") == "1"
    return DSAlerter(dsa_path=pcfg.dsa_path, dry_run=dry)


def _metering(store):
    from unlockaid.commercial.plans import Metering
    return Metering(store)


def make_meter(store, plan):
    """Uniform meter callback: fn(workspace, metric, qty, ref).

    research/inference quotas are enforced pre-flight (see `preflight_quota`)
    and raise here if a run exceeds plan limits. `alerts_delivered` is recorded
    *after* delivery without raising — messages already went out, so a quota
    breach must surface as billable usage, never as a failed run (H3 fix).
    """
    mt = _metering(store)
    quota = {"research_jobs": mt.research, "inference_jobs": mt.inference}

    def meter(workspace_id, metric, qty=1, ref=""):
        hook = quota.get(metric)
        if hook:
            for _ in range(int(qty)):
                try:
                    hook(workspace_id, plan, ref)
                except Exception as e:  # QuotaError post-hoc: record, don't abort
                    logger.warning("quota check after completed work (%s): %s; "
                                   "recording usage as overage", metric, e)
                    store.meter(workspace_id, metric + "_overage", 1, ref)
        else:
            store.meter(workspace_id, metric, qty, ref)
    return meter


def preflight_quota(store, cfg, metric: str, qty: int = 1) -> None:
    """Raise QuotaError BEFORE work starts (research/daily commands)."""
    from unlockaid.commercial.plans import Metering
    Metering(store).check_quota(cfg.workspace_id, cfg.plan, metric, qty)


def cap_alert_budget(store, cfg):
    """Unify the two alert budgets: workspace prefs may not exceed the plan's
    per-day ceiling — the plan quota is the single source of truth."""
    from unlockaid.commercial.plans import Metering
    cfg.alerts.max_alerts_per_day = min(
        cfg.alerts.max_alerts_per_day, Metering.effective_alert_budget(cfg.plan))
    return cfg


# ---------------- commands ----------------
def cmd_data_refresh(args):
    from unlockaid.data.health import refresh_dump
    pcfg, store, _ = _ctx()
    info = refresh_dump(os.path.expanduser(pcfg.qlib_provider_uri), force=args.force)
    print(json.dumps(info, indent=2))


def cmd_data_health(args):
    pcfg, store, engine = _ctx()
    from unlockaid.data.health import check_health
    cfg = _load_ws(pcfg, args.workspace)
    insts = cfg.instruments or engine.list_instruments(
        cfg.universe, cfg.handler_range[0], cfg.handler_range[1])[:30]
    rep = check_health(engine, cfg.universe, insts)
    store.put_data_health(cfg.workspace_id, rep.calendar_last or "",
                          "ok" if rep.fresh else "stale",
                          {"stale": rep.stale_count, "anomaly": rep.anomaly_count})
    print(json.dumps({"calendar_last": rep.calendar_last, "fresh": rep.fresh,
                      "stale": rep.stale_count, "anomaly": rep.anomaly_count,
                      "missing": len(rep.failed),
                      "examples": [a.__dict__ for a in rep.assets[:5]]},
                     indent=2, default=str))


def cmd_init_workspace(args):
    pcfg, store, _ = _ctx()
    instruments = args.instruments.split(",") if args.instruments else []
    watchlist = args.watchlist.split(",") if args.watchlist else instruments[:20]
    portfolio = [{"instrument": i, "weight": 1.0 / max(1, len(watchlist))}
                 for i in watchlist] if args.portfolio else []
    cfg = WorkspaceConfig(
        workspace_id=args.workspace, name=args.name or args.workspace,
        plan=args.plan, universe=args.universe, instruments=instruments,
        watchlist=watchlist, portfolio=portfolio,
        hyperparameters={"learning_rate": 0.05, "num_leaves": 64,
                         "colsample_bytree": 0.88, "subsample": 0.88,
                         "num_boost_round": 200, "early_stopping_rounds": 50,
                         "n_jobs": pcfg.train_n_jobs},
        alerts=AlertPrefs(channels=args.channels.split(","),
                          max_alerts_per_day=args.max_alerts),
        schedule_time=args.schedule)
    cfg.save(Path(pcfg.workspace_dir) / f"{args.workspace}.yaml")
    store.put_customer(args.workspace, args.email or f"{args.workspace}@example.com",
                       args.plan)
    print(f"workspace '{args.workspace}' created: "
          f"{Path(pcfg.workspace_dir)/f'{args.workspace}.yaml'}")


def cmd_research(args):
    pcfg, store, engine = _ctx()
    from unlockaid.research.runner import ResearchRunner
    cfg = _load_ws(pcfg, args.workspace)
    preflight_quota(store, cfg, "research_jobs")
    runner = ResearchRunner(engine, store, pcfg.artifact_dir)
    rec = runner.train(cfg, meter=make_meter(store, cfg.plan))
    bt = runner.run_result(rec.model_id)["backtest"]
    ic = runner.run_result(rec.model_id)["ic"]
    print(json.dumps({"model_id": rec.model_id, "status": rec.status.value,
                      "experiment_ref": rec.experiment_ref,
                      "ic": ic, "backtest": {k: bt[k] for k in
                       ("ann_return", "information_ratio", "max_drawdown",
                        "mean_turnover")}}, indent=2))


def cmd_validate(args):
    pcfg, store, engine = _ctx()
    from unlockaid.agents.research import OverfitAuditAgent
    from unlockaid.research.runner import ResearchRunner
    cfg = _load_ws(pcfg, args.workspace)
    runner = ResearchRunner(engine, store, pcfg.artifact_dir)
    if not runner.run_result(args.model):
        # No in-memory run for this id (fresh process): qlib training from the
        # same workspace config is deterministic given the same data window, so
        # re-run research and validate the freshly registered candidate.
        rec = runner.train(cfg, meter=make_meter(store, cfg.plan))
        print(f"(no in-memory run for {args.model}; validated fresh candidate {rec.model_id})")
        args.model = rec.model_id
    val = runner.validate(cfg, args.model, meter=make_meter(store, cfg.plan))
    extra = OverfitAuditAgent().audit(val.to_dict())
    print(json.dumps({"model_id": val.model_id, "passed": val.passed,
                      "metrics": val.metrics, "gates": val.gate_results,
                      "overfit_flags": val.overfit_flags + extra,
                      "stability": val.stability}, indent=2, default=float))


def cmd_deploy(args):
    pcfg, store, _ = _ctx()
    cfg = _load_ws(pcfg, args.workspace)
    rec = store.get_model(args.model)
    if rec is None:
        sys.exit(f"model {args.model} not in registry")
    if rec["status"] != "validated" and not args.force:
        sys.exit(f"model {args.model} is '{rec['status']}'; only validated models "
                 "deploy (§24 fail-safe). Use --force to override.")
    store.set_deployment(cfg.workspace_id, args.model, True,
                         args.schedule or cfg.schedule_time)
    print(f"deployed {args.model} to {cfg.workspace_id} "
          f"(daily {args.schedule or cfg.schedule_time} Asia/Shanghai)")


def cmd_daily(args):
    pcfg, store, engine = _ctx()
    from unlockaid.alerts.intelligence import AlertIntelligence
    from unlockaid.analysis.daily import DailyPipeline
    cfg = _load_ws(pcfg, args.workspace)
    cap_alert_budget(store, cfg)
    alerter = _alerter(pcfg)
    intel = AlertIntelligence(store, alerter, cfg.alerts)
    pipe = DailyPipeline(engine, store, intel)
    res = pipe.run(cfg, asof=args.asof,
                   meter=None if args.no_meter else make_meter(store, cfg.plan))
    d = res.to_dict()
    print(json.dumps({k: d[k] for k in
                      ("workspace_id", "asof", "ok", "model_id", "n_predictions",
                       "engine_sources", "error")}, indent=2))
    print("--- alerts ---")
    for a in d["alerts"]:
        print(f"  [{a['severity']:8s}] value={a['score']:.2f} "
              f"{'DELIVERED' if a['deliver'] else 'suppressed:' + str(a['suppress_reason'])}"
              f" — {a['title']}")


def cmd_alert_test(args):
    pcfg, store, _ = _ctx()
    cfg = _load_ws(pcfg, args.workspace)
    alerter = _alerter(pcfg)
    md = (f"### UnlockAid delivery test\n\nWorkspace **{cfg.workspace_id}** "
          f"alert pipeline is wired. Channel set: {', '.join(cfg.alerts.channels)}.")
    results = alerter.dispatch(md, args.channels.split(",") if args.channels
                               else cfg.alerts.channels, severity="info")
    print(json.dumps({"engine_source": f"unlockaid+{alerter.engine_source}",
                      "results": results}, indent=2))
    if not any(results.values()):
        sys.exit(1)


def cmd_serve(args):
    pcfg, store, _ = _ctx()
    import uvicorn

    from unlockaid.dashboard.app import build_app
    app = build_app(pcfg, store)
    if args.cron:
        from unlockaid.alerts.intelligence import AlertIntelligence
        from unlockaid.analysis.daily import DailyPipeline
        from unlockaid.deploy.scheduler import DeployScheduler
        sched_store = store
        sch = DeployScheduler(
            sched_store,
            run_fn=lambda cfg: DailyPipeline(
                QlibEngine(os.path.expanduser(pcfg.qlib_provider_uri)), sched_store,
                AlertIntelligence(sched_store, _alerter(pcfg), cfg.alerts)
            ).run(cfg),
            config_loader=lambda ws: WorkspaceConfig.load(
                Path(pcfg.workspace_dir) / f"{ws}.yaml"))
        jobs = sch.sync()
        sch.start()
        print(f"scheduler jobs: {jobs}")
    print(f"UnlockAid dashboard on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


def cmd_scorecard(args):
    pcfg, store, _ = _ctx()
    print(json.dumps(store.scorecard(args.workspace), indent=2))


def cmd_economics(args):
    pcfg, store, _ = _ctx()
    from unlockaid.commercial.plans import PLANS, contribution_margin
    cust = store.get_customer(args.workspace)
    plan = (args.plan or (cust or {}).get("plan", "free"))
    print(json.dumps(contribution_margin(store, args.workspace, plan), indent=2))
    print("plan limits:", json.dumps(PLANS[plan]))


def cmd_registry(args):
    pcfg, store, _ = _ctx()
    if args.model:
        print(json.dumps(store.get_model(args.model), indent=2))
    else:
        rows = store.list_models(args.workspace or None)
        print(json.dumps([{k: r[k] for k in
                           ("model_id", "name", "version", "status",
                            "experiment_ref", "created_at", "engine_source")}
                          for r in rows], indent=2))


def cmd_e2e(args):
    """The full MVP loop (§12): universe → train → backtest → validate →
    register → deploy → daily → alert → dashboard payload."""
    pcfg, store, engine = _ctx()
    from unlockaid.alerts.intelligence import AlertIntelligence
    from unlockaid.analysis.daily import DailyPipeline
    from unlockaid.research.runner import ResearchRunner
    ws = args.workspace
    cfg = _load_ws(pcfg, ws)
    cap_alert_budget(store, cfg)
    preflight_quota(store, cfg, "research_jobs", qty=2)  # train + walk-forward folds
    runner = ResearchRunner(engine, store, pcfg.artifact_dir)
    meter = make_meter(store, cfg.plan)
    rec = runner.train(cfg, meter=meter)
    val = runner.validate(cfg, rec.model_id, meter=meter)
    print(f"[1/4] research+validate: {rec.model_id} passed={val.passed} "
          f"ic={val.metrics['ic']:.4f} IR={val.metrics['information_ratio']:.2f}")
    if not val.passed and not args.force:
        sys.exit(
            f"E2E STOPPED: model {rec.model_id} failed validation "
            f"({val.overfit_flags}) — not deploying. Fail-safe §24; "
            "the research→validate loop still proved out above. "
            "Use --force to deploy anyway.")
    store.set_deployment(ws, rec.model_id, True, cfg.schedule_time)
    alerter = _alerter(pcfg)
    pipe = DailyPipeline(engine, store, AlertIntelligence(store, alerter, cfg.alerts))
    res = pipe.run(cfg, meter=make_meter(store, cfg.plan))
    n_del = sum(1 for a in res.alerts if a.deliver)
    print(f"[2/4] deployed + daily inference: {len(res.predictions)} predictions, ok={res.ok}")
    print(f"[3/4] alerts: {len(res.alerts)} events, {n_del} delivered "
          f"via {alerter.engine_source}")
    run = store.latest_daily_run(ws)
    payload = json.loads(run["payload"])
    Path(pcfg.data_dir, "exports").mkdir(parents=True, exist_ok=True)
    out = Path(pcfg.data_dir, "exports", f"e2e_{ws}.json")
    out.write_text(json.dumps(payload, indent=2))
    print(f"[4/4] dashboard payload exported: {out}")
    if not res.ok:
        sys.exit("E2E FAILED: daily run error: " + str(res.error))
    print("E2E_OK")


def cmd_discover(args):
    """§6 Factor Discovery Agent: rank single-factor ICs on real qlib data."""
    pcfg, store, engine = _ctx()
    from unlockaid.agents.research import FactorDiscoveryAgent
    cfg = _load_ws(pcfg, args.workspace)
    results = FactorDiscoveryAgent(engine).evaluate(
        cfg.universe, args.start, args.end)
    print(json.dumps(results, indent=2))
    n_pass = sum(1 for r in results if r["pass"])
    print(f"{n_pass}/{len(results)} factors pass |rank_ic|>=0.01 "
          f"(qlib expressions, csi universe, {args.start}..{args.end})")


def cmd_experiments(args):
    """§6 Experiment Agent: fan out a hyperparameter grid through the real
    research loop (each job is quota-metered), rank results by IR."""
    pcfg, store, engine = _ctx()
    import copy

    from unlockaid.agents.research import ExperimentAgent
    from unlockaid.research.runner import ResearchRunner
    cfg = _load_ws(pcfg, args.workspace)
    runner = ResearchRunner(engine, store, pcfg.artifact_dir)
    grid = ExperimentAgent(runner).plan(cfg.hyperparameters,
                          cfg.model_type)[:args.max_runs]
    meter = make_meter(store, cfg.plan)
    rows = []
    for hp in grid:
        c = copy.deepcopy(cfg)
        c.hyperparameters = hp
        try:
            rec = runner.train(c, meter=meter)
            res = runner.run_result(rec.model_id)
            rows.append({"hp": {k: hp[k] for k in sorted(hp)},
                         "model_id": rec.model_id,
                         "ic": res["ic"]["ic"],
                         "ann_return": res["backtest"]["ann_return"],
                         "information_ratio": res["backtest"]["information_ratio"],
                         "max_drawdown": res["backtest"]["max_drawdown"]})
        except Exception as e:
            rows.append({"hp": hp, "error": str(e)[:200]})
    rows.sort(key=lambda r: -r.get("information_ratio", -9e9))
    print(json.dumps(rows, indent=2))


def cmd_explain(args):
    """§6 Research Explanation Agent: customer prose from real run artifacts."""
    pcfg, store, _ = _ctx()
    from unlockaid.agents.research import ResearchExplanationAgent
    cfg = _load_ws(pcfg, args.workspace)
    rec = store.get_model(args.model)
    if rec is None:
        sys.exit(f"model {args.model} not in registry")
    import json as _j
    bt = _j.load(open(Path(rec["artifact_path"]) / "backtest.json"))
    val = rec["validation"] or {"passed": False, "overfit_flags": ["not validated"]}
    ic = {k: val["metrics"][k] for k in ("ic", "rank_ic")} | {"n": val["metrics"]["n_oos"]}
    print(ResearchExplanationAgent().explain_run(
        f"{cfg.name} [{cfg.model_type}/{cfg.factor_set}]", bt, ic, val))



def main(argv=None):
    _configure_logging()
    ap = argparse.ArgumentParser(prog="unlockaid",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version=f"unlockaid {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("data", help="Layer A data ops")
    dsub = d.add_subparsers(dest="sub", required=True)
    r = dsub.add_parser("refresh"); r.add_argument("--force", action="store_true")
    r.set_defaults(fn=cmd_data_refresh)
    h = dsub.add_parser("health"); h.add_argument("workspace")
    h.set_defaults(fn=cmd_data_health)

    i = sub.add_parser("init-workspace")
    i.add_argument("workspace")
    i.add_argument("--name")
    i.add_argument("--plan", default="free")
    i.add_argument("--universe", default="csi300")
    i.add_argument("--instruments", default="")
    i.add_argument("--watchlist", default="")
    i.add_argument("--portfolio", action="store_true")
    i.add_argument("--channels", default="custom_webhook")
    i.add_argument("--max-alerts", type=int, default=5)
    i.add_argument("--schedule", default="17:30")
    i.add_argument("--email", default="")
    i.set_defaults(fn=cmd_init_workspace)

    x = sub.add_parser("research"); x.add_argument("workspace")
    x.set_defaults(fn=cmd_research)
    v = sub.add_parser("validate"); v.add_argument("workspace"); v.add_argument("model")
    v.set_defaults(fn=cmd_validate)
    p = sub.add_parser("deploy"); p.add_argument("workspace"); p.add_argument("model")
    p.add_argument("--schedule"); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_deploy)
    y = sub.add_parser("daily"); y.add_argument("workspace")
    y.add_argument("--no-meter", action="store_true")
    y.add_argument("--asof", default=None, help="business date YYYY-MM-DD (backfill)")
    y.set_defaults(fn=cmd_daily)
    t = sub.add_parser("alert-test"); t.add_argument("workspace")
    t.add_argument("--channels", default="")
    t.set_defaults(fn=cmd_alert_test)
    s = sub.add_parser("serve"); s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int,
                   default=int(os.environ.get("UNLOCKAID_PORT", "8765")))
    s.add_argument("--cron", action="store_true")
    s.set_defaults(fn=cmd_serve)
    sc = sub.add_parser("scorecard"); sc.add_argument("workspace")
    sc.set_defaults(fn=cmd_scorecard)
    ec = sub.add_parser("economics"); ec.add_argument("workspace")
    ec.add_argument("--plan")
    ec.set_defaults(fn=cmd_economics)
    rg = sub.add_parser("registry"); rg.add_argument("--workspace")
    rg.add_argument("--model")
    rg.set_defaults(fn=cmd_registry)
    dc = sub.add_parser("discover"); dc.add_argument("workspace")
    dc.add_argument("--start", default="2025-01-01"); dc.add_argument("--end", default="2026-08-01")
    dc.set_defaults(fn=cmd_discover)
    xp = sub.add_parser("experiments"); xp.add_argument("workspace")
    xp.add_argument("--max-runs", type=int, default=4)
    xp.set_defaults(fn=cmd_experiments)
    ex = sub.add_parser("explain"); ex.add_argument("workspace"); ex.add_argument("model")
    ex.set_defaults(fn=cmd_explain)
    e = sub.add_parser("e2e"); e.add_argument("workspace")
    e.add_argument("--force", action="store_true",
                   help="deploy even if validation rejects the model")
    e.set_defaults(fn=cmd_e2e)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()

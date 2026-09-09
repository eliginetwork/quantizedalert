"""Commercial layer — plans, quotas, usage metering, unit economics (§9, §22).

Revenue is only meaningful against real costs, so the same module computes
contribution margin per customer from the metering table. Stripe integration
is a thin adapter: webhook-driven plan changes + metering uploads, fully testable
offline (no network in tests).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date

from unlockaid.store import Store

# §9 pricing (validated against the cost model below; not yet validated with customers)
PLANS: dict[str, dict] = {
    "free": {
        "price_month_usd": 0,
        "max_portfolios": 1,
        "research_jobs_month": 5,
        "inference_jobs_month": 30,
        "alerts_day": 2,
        "channels": ["custom_webhook", "ntfy", "gotify"],
        "features": ["daily_analysis", "basic_dashboard"],
    },
    "individual": {
        "price_month_usd": 49,
        "max_portfolios": 1,
        "research_jobs_month": 20,
        "inference_jobs_month": 200,
        "alerts_day": 5,
        "channels": ["telegram", "slack", "discord", "custom_webhook", "ntfy",
                     "pushover", "gotify", "serverchan3", "pushplus"],
        "features": ["daily_analysis", "dashboard", "walk_forward", "drift_monitoring"],
    },
    "professional": {
        "price_month_usd": 299,
        "max_portfolios": 5,
        "research_jobs_month": 100,
        "inference_jobs_month": 1000,
        "alerts_day": 20,
        "channels": "*",
        "features": ["*", "sensitivity_checks", "api_access"],
    },
    "team": {
        "price_month_usd": 1200,
        "max_portfolios": 25,
        "research_jobs_month": 500,
        "inference_jobs_month": 5000,
        "alerts_day": 100,
        "channels": "*",
        "features": ["*", "shared_registry", "permissions", "audit_log"],
    },
    "enterprise": {
        "price_month_usd": 0,   # custom annual contract
        "max_portfolios": 10**9,
        "research_jobs_month": 10**9,
        "inference_jobs_month": 10**9,
        "alerts_day": 10**9,
        "channels": "*",
        "features": ["*"],
    },
}

# §22 unit economics — monthly cost model calibrated to this host's real profile:
# a 20-core box trains full CSI300 Alpha158 in ~10s; cloud 8 vCPU ≈ $0.12/h.
COST_PER_RESEARCH_JOB = 0.05      # CPU per training run
COST_PER_INFERENCE = 0.002        # daily score on cached dataset
COST_DATA_DUMP = 3.0              # qlib bin dump refresh (shared, per-customer share)
COST_DB_STORAGE = 0.5             # sqlite on managed volume
COST_MESSAGING_PER_ALERT = 0.001  # webhook push ≈ free; SMTP ≈ $0.0006
COST_COMPUTE_BASE = 12.0          # always-on worker+dashboard box


@dataclass
class QuotaError(Exception):
    workspace_id: str
    metric: str
    used: float
    limit: float

    def __str__(self) -> str:
        return (f"quota exceeded: {self.workspace_id} {self.metric} "
                f"{self.used:.0f}/{self.limit:.0f}")


class Metering:
    """Quota-gated usage metering backed by the store's usage table."""

    def __init__(self, store: Store):
        self.store = store

    @staticmethod
    def month_start() -> str:
        return date.today().replace(day=1).isoformat()

    def check_quota(self, workspace_id: str, plan: str, metric: str,
                    qty: float = 1) -> None:
        """Pre-flight quota check WITHOUT metering — call before starting work
        so a quota breach never aborts work that already happened."""
        limits = {"research_jobs": PLANS[plan]["research_jobs_month"],
                  "inference_jobs": PLANS[plan]["inference_jobs_month"],
                  "alerts_day": PLANS[plan]["alerts_day"]}
        if metric not in limits:
            return
        if metric == "alerts_day":
            used = self.store.usage_by_day(workspace_id, "alerts_delivered",
                                           date.today().isoformat())
        else:
            used = self.store.usage_total(workspace_id, metric, self.month_start())
        if used + qty > limits[metric]:
            raise QuotaError(workspace_id, metric, used, limits[metric])

    def check_and_meter(self, workspace_id: str, plan: str, metric: str,
                        qty: float = 1, ref: str = "") -> None:
        limits = {"research_jobs": PLANS[plan]["research_jobs_month"],
                  "inference_jobs": PLANS[plan]["inference_jobs_month"]}
        if metric in limits:
            used = self.store.usage_total(workspace_id, metric, self.month_start())
            if used + qty > limits[metric]:
                raise QuotaError(workspace_id, metric, used, limits[metric])
        self.store.meter(workspace_id, metric, qty, ref)

    @staticmethod
    def effective_alert_budget(plan: str) -> int:
        """Plan-level per-day alert ceiling — the single source of truth that
        workspace alert prefs must be capped to (prevents two disagreeing
        budgets: one at dispatch time, one at metering time)."""
        return int(PLANS[plan]["alerts_day"])

    def research(self, workspace_id: str, plan: str, ref: str = "") -> None:
        self.check_and_meter(workspace_id, plan, "research_jobs", 1, ref)

    def inference(self, workspace_id: str, plan: str, ref: str = "") -> None:
        self.check_and_meter(workspace_id, plan, "inference_jobs", 1, ref)

    def alert(self, workspace_id: str, plan: str, ref: str = "") -> None:
        today = date.today().isoformat()
        used = self.store.usage_by_day(workspace_id, "alerts_delivered", today)
        if used >= PLANS[plan]["alerts_day"]:
            raise QuotaError(workspace_id, "alerts_day", used,
                             PLANS[plan]["alerts_day"])
        self.store.meter(workspace_id, "alerts_delivered", 1, ref)


def contribution_margin(store: Store, workspace_id: str, plan: str,
                        month: str | None = None) -> dict:
    """§22: Revenue − data − compute − storage − messaging = contribution."""
    month_start = month or date.today().replace(day=1).isoformat()
    p = PLANS[plan]
    revenue = p["price_month_usd"]
    research = store.usage_total(workspace_id, "research_jobs", month_start)
    inference = store.usage_total(workspace_id, "inference_jobs", month_start)
    alerts = store.usage_total(workspace_id, "alerts_delivered", month_start)
    data_cost = COST_DATA_DUMP
    compute = research * COST_PER_RESEARCH_JOB + inference * COST_PER_INFERENCE
    messaging = alerts * COST_MESSAGING_PER_ALERT
    total_cost = data_cost + compute + COST_DB_STORAGE + messaging
    margin = revenue - total_cost
    return {
        "workspace_id": workspace_id, "plan": plan,
        "revenue": revenue,
        "costs": {"data": round(data_cost, 4),
                  "research_compute": round(research * COST_PER_RESEARCH_JOB, 4),
                  "inference_compute": round(inference * COST_PER_INFERENCE, 4),
                  "storage": COST_DB_STORAGE,
                  "messaging": round(messaging, 4)},
        "total_cost": round(total_cost, 4),
        "contribution": round(margin, 4),
        "margin_pct": round(margin / revenue * 100, 1) if revenue else None,
        "usage": {"research_jobs": research, "inference_jobs": inference,
                  "alerts_delivered": alerts},
    }


class StripeAdapter:
    """Stripe Billing surface: customers, subscriptions, usage records, webhooks.

    stripe SDK is injected/created lazily so offline tests use a fake client.
    Env: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
         UNLOCKAID_STRIPE_PRICES='{"individual":"price_xxx", ...}'.
    """

    def __init__(self, store: Store, client=None):
        self.store = store
        if client is None:
            import stripe  # lazy import keeps offline tests green
            client = stripe
        self.stripe = client

    def create_customer(self, workspace_id: str, email: str) -> dict:
        c = self.stripe.Customer.create(email=email, name=workspace_id)
        self.store.put_customer(workspace_id, email, "free",
                                stripe_customer_id=c["id"])
        return c

    def subscribe(self, workspace_id: str, plan: str) -> dict:
        cust = self.store.get_customer(workspace_id)
        price_id = _price_ids().get(plan)
        if not price_id:
            raise ValueError(f"no stripe price configured for plan {plan}")
        sub = self.stripe.Subscription.create(
            customer=cust["stripe_customer_id"], items=[{"price": price_id}])
        self.store.set_customer_plan(workspace_id, plan,
                                     stripe_subscription_id=sub["id"])
        return sub

    def report_usage(self, workspace_id: str, metric: str, qty: float) -> dict | None:
        """Usage-based billing v2 meter event (per-customer cost visibility)."""
        cust = self.store.get_customer(workspace_id)
        if not cust or not cust.get("stripe_customer_id"):
            return None
        return self.stripe.billing.MeterEvent.record(
            event_name=f"unlockaid_{metric}",
            payload={"stripe_customer_id": cust["stripe_customer_id"],
                     "value": str(qty)})

    def handle_webhook(self, payload: bytes, sig_header: str) -> dict:
        """Plan changes land here: checkout.session.completed / subscription.updated."""
        event = self.stripe.Webhook.construct_event(
            payload, sig_header, _webhook_secret())
        t = event["type"]
        if t in ("checkout.session.completed", "customer.subscription.updated"):
            obj = event["data"]["object"]
            ws = obj.get("client_reference_id") or obj.get("metadata", {}).get("workspace_id")
            plan = (obj.get("metadata") or {}).get("plan")
            if ws and plan:
                self.store.set_customer_plan(
                    ws, plan,
                    stripe_subscription_id=obj.get("subscription") or obj.get("id"))
        return {"received": True, "type": t}


def _price_ids() -> dict[str, str]:
    import json
    import os
    raw = os.environ.get("UNLOCKAID_STRIPE_PRICES", "{}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _webhook_secret() -> str:
    import os
    return os.environ.get("STRIPE_WEBHOOK_SECRET", "")


def _now() -> int:
    from datetime import datetime
    return int(datetime.now(UTC).timestamp())

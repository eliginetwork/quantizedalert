"""Stripe adapter contract, verified against an injected fake client."""
import pytest

from quantizedalert.commercial.plans import StripeAdapter
from quantizedalert.store import Store


class FakeStripe:
    class Customer:
        @staticmethod
        def create(email, name):
            return {"id": f"cus_{name}"}

    class Subscription:
        @staticmethod
        def create(customer, items):
            return {"id": "sub_1", "items": {"data": [{"price": items[0]["price"]}]}}

    class billing:
        class MeterEvent:
            @staticmethod
            def record(event_name, payload):
                return {"recorded": event_name, **payload}

    class Webhook:
        @staticmethod
        def construct_event(payload, sig_header, secret):
            import json
            return json.loads(payload)


@pytest.fixture()
def adapter(tmp_path):
    store = Store(str(tmp_path / "b.db"))
    return StripeAdapter(store, client=FakeStripe()), store


def test_customer_and_subscribe_flow(adapter, monkeypatch):
    a, store = adapter
    c = a.create_customer("w1", "x@y.z")
    assert c["id"] == "cus_w1"
    monkeypatch.setenv("QUANTIZEDALERT_STRIPE_PRICES", '{"individual": "price_ind"}')
    sub = a.subscribe("w1", "individual")
    assert sub["id"] == "sub_1"
    cust = store.get_customer("w1")
    assert cust["plan"] == "individual"
    assert cust["stripe_subscription_id"] == "sub_1"


def test_customer_and_subscribe_legacy_env_fallback(adapter, monkeypatch):
    a, store = adapter
    c = a.create_customer("w1_legacy", "x@y.z")
    assert c["id"] == "cus_w1_legacy"
    monkeypatch.delenv("QUANTIZEDALERT_STRIPE_PRICES", raising=False)
    monkeypatch.setenv("UNLOCKAID_STRIPE_PRICES", '{"individual": "price_ind_legacy"}')
    sub = a.subscribe("w1_legacy", "individual")
    assert sub["id"] == "sub_1"
    cust = store.get_customer("w1_legacy")
    assert cust["plan"] == "individual"
    assert cust["stripe_subscription_id"] == "sub_1"


def test_meter_event_reports_real_metric(adapter):
    a, store = adapter
    a.create_customer("w2", "u@v.w")
    r = a.report_usage("w2", "inference_jobs", 7)
    assert r["recorded"] == "quantizedalert_inference_jobs"
    assert r["value"] == "7"


def test_subscribe_unknown_plan_raises(adapter, monkeypatch):
    a, _ = adapter
    a.create_customer("w3", "a@b.c")
    monkeypatch.setenv("QUANTIZEDALERT_STRIPE_PRICES", '{"individual": "price_ind"}')
    with pytest.raises(ValueError, match="unknown plan"):
        a.subscribe("w3", "does_not_exist")


def test_subscribe_missing_price_raises(adapter, monkeypatch):
    a, _ = adapter
    a.create_customer("w4", "d@e.f")
    monkeypatch.setenv("QUANTIZEDALERT_STRIPE_PRICES", '{"individual": "price_ind"}')
    with pytest.raises(ValueError, match="no stripe price"):
        a.subscribe("w4", "professional")


def test_report_usage_no_customer_returns_none(adapter):
    a, _ = adapter
    assert a.report_usage("ghost", "inference_jobs", 1) is None


def test_report_usage_float_precision(adapter):
    a, _ = adapter
    a.create_customer("w5", "g@h.i")
    r = a.report_usage("w5", "inference_jobs", 0.1 + 0.2)
    # Must be "0.30000000000000004" -> NO, must be "0.3"
    assert r["value"] == "0.3", f"float noise leaked: {r['value']}"


def test_price_ids_invalid_json_raises(monkeypatch):
    from quantizedalert.commercial.plans import _price_ids
    monkeypatch.delenv("QUANTIZEDALERT_STRIPE_PRICES", raising=False)
    monkeypatch.setenv("UNLOCKAID_STRIPE_PRICES", "{not json}")
    with pytest.raises(ValueError, match="not valid JSON"):
        _price_ids()


def test_handle_webhook_invalid_signature(adapter, monkeypatch):
    a, _ = adapter
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")

    class BadWebhook:
        @staticmethod
        def construct_event(payload, sig_header, secret):
            raise ValueError("invalid signature")

    a.stripe = type("S", (), {"Webhook": BadWebhook, "Customer": FakeStripe.Customer,
                               "Subscription": FakeStripe.Subscription, "billing": FakeStripe.billing})()
    with pytest.raises(ValueError, match="invalid signature"):
        a.handle_webhook(b"{}", "bad_sig")


def test_enterprise_quota_is_effectively_unlimited(tmp_path):
    from quantizedalert.commercial.plans import Metering
    store = Store(str(tmp_path / "e.db"))
    m = Metering(store)
    # Enterprise has 1e9 quota — metering 1e6 jobs must not raise
    for _ in range(100):
        m.check_and_meter("w", "enterprise", "research_jobs", 10000, ref="bulk")
    # Should not have raised
    assert store.usage_total("w", "research_jobs", m.month_start()) == 100 * 10000

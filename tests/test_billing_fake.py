"""Stripe adapter contract, verified against an injected fake client."""
import pytest
from unlockaid.store import Store
from unlockaid.commercial.plans import StripeAdapter


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


@pytest.fixture()
def adapter(tmp_path):
    store = Store(str(tmp_path / "b.db"))
    return StripeAdapter(store, client=FakeStripe()), store


def test_customer_and_subscribe_flow(adapter):
    a, store = adapter
    c = a.create_customer("w1", "x@y.z")
    assert c["id"] == "cus_w1"
    import os
    os.environ["UNLOCKAID_STRIPE_PRICES"] = '{"individual": "price_ind"}'
    sub = a.subscribe("w1", "individual")
    assert sub["id"] == "sub_1"
    cust = store.get_customer("w1")
    assert cust["plan"] == "individual"
    assert cust["stripe_subscription_id"] == "sub_1"


def test_meter_event_reports_real_metric(adapter):
    a, store = adapter
    a.create_customer("w2", "u@v.w")
    r = a.report_usage("w2", "inference_jobs", 7)
    assert r["recorded"] == "unlockaid_inference_jobs"
    assert r["value"] == "7"

"""Testes unitários do gerador de eventos de e-commerce (generator/01gerador.py)."""
import importlib.util
import os
import sys

MODULE_PATH = os.path.join(os.path.dirname(__file__), "..", "generator", "01gerador.py")

spec = importlib.util.spec_from_file_location("gerador", MODULE_PATH)
gerador = importlib.util.module_from_spec(spec)
sys.modules["gerador"] = gerador
spec.loader.exec_module(gerador)

REQUIRED_FIELDS = {
    "event_id", "timestamp", "user_id", "product_id", "product_name",
    "category", "action", "price", "delivery_status",
}


def test_generate_event_has_all_required_fields():
    event = gerador.generate_event()
    assert REQUIRED_FIELDS.issubset(event.keys())


def test_generate_event_action_is_valid():
    for _ in range(50):
        event = gerador.generate_event()
        assert event["action"] in gerador.ACTIONS


def test_generate_event_product_matches_category():
    for _ in range(50):
        event = gerador.generate_event()
        products_in_category = {p["id"] for p in gerador.CATEGORIES_PRODUCTS[event["category"]]}
        assert event["product_id"] in products_in_category


def test_generate_event_delivery_status_only_when_relevant():
    for _ in range(200):
        event = gerador.generate_event()
        if event["action"] == "delivery_status_update":
            assert event["delivery_status"] in gerador.DELIVERY_STATUSES
        else:
            assert event["delivery_status"] is None


def test_generate_event_timestamp_is_isoformat():
    from datetime import datetime
    event = gerador.generate_event()
    # Não deve lançar exceção ao fazer o parse do timestamp.
    datetime.fromisoformat(event["timestamp"])

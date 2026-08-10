"""Tests for Stripe Payment Link offer plumbing without calling Stripe."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "create_stripe_payment_links.py"
spec = importlib.util.spec_from_file_location("create_stripe_payment_links", SCRIPT)
stripe_connector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stripe_connector)


class TestStripeConnector(unittest.TestCase):
    def test_amount_to_minor_units(self):
        self.assertEqual(stripe_connector.amount_to_minor_units("19.00"), 1900)
        self.assertEqual(stripe_connector.amount_to_minor_units("99.00"), 9900)

    def test_build_creation_plan(self):
        offer = {
            "offer_id": "sample-conversion",
            "name": "Sample Conversion",
            "summary": "Convert a sample document.",
            "price": {"amount": "19.00", "currency": "EUR"},
            "source_repository": "https://github.com/wesseltl/pdf-mcp",
        }
        plan = stripe_connector.build_creation_plan(offer)
        self.assertEqual(plan["product"]["name"], "Sample Conversion")
        self.assertEqual(plan["price"]["unit_amount"], 1900)
        self.assertEqual(plan["price"]["currency"], "eur")
        self.assertEqual(plan["payment_link"]["line_items"], [{"quantity": 1}])

    def test_upsert_stripe_method(self):
        offer = {
            "checkout_url": None,
            "purchase_methods": [
                {"type": "email_purchase_request", "url": "mailto:test@example.com"}
            ],
            "agent_instructions": {"recommended_action": "old"},
        }
        stripe_connector.upsert_stripe_method(offer, "https://buy.stripe.com/test")
        self.assertEqual(offer["checkout_url"], "https://buy.stripe.com/test")
        self.assertEqual(offer["purchase_methods"][0]["type"], "stripe_payment_link")
        self.assertTrue(offer["purchase_methods"][0]["requires_user_confirmation"])

    def test_dry_run_does_not_write_offer_file(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "offer.json")
        offer = {
            "offer_id": "sample-conversion",
            "name": "Sample Conversion",
            "summary": "Convert a sample document.",
            "price": {"amount": "19.00", "currency": "EUR"},
            "source_repository": "https://github.com/wesseltl/pdf-mcp",
            "checkout_url": None,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(offer, f)
        result = stripe_connector.process_offer(Path(path), live=False, write=True, force=False)
        self.assertEqual(result["status"], "dry_run")
        with open(path, encoding="utf-8") as f:
            unchanged = json.load(f)
        self.assertIsNone(unchanged["checkout_url"])


if __name__ == "__main__":
    unittest.main()

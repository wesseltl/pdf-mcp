"""Tests for Stripe Payment Link offer plumbing without calling Stripe."""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "create_stripe_payment_links.py"
spec = importlib.util.spec_from_file_location("create_stripe_payment_links", SCRIPT)
stripe_connector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stripe_connector)


class TestStripeConnector(unittest.TestCase):
    def test_amount_to_minor_units(self):
        self.assertEqual(stripe_connector.amount_to_minor_units("19.00"), 1900)
        self.assertEqual(stripe_connector.amount_to_minor_units("99.00"), 9900)

    def test_stripe_key_mode(self):
        self.assertEqual(stripe_connector.stripe_key_mode("sk_test_example"), "test")
        self.assertEqual(stripe_connector.stripe_key_mode("rk_live_example"), "live")
        with self.assertRaises(ValueError):
            stripe_connector.stripe_key_mode("pk_test_not_a_secret")

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
        self.assertEqual(plan["price"]["tax_behavior"], "exclusive")
        self.assertEqual(plan["payment_link"]["line_items"], [{"quantity": 1}])
        self.assertTrue(plan["payment_link"]["automatic_tax"]["enabled"])
        self.assertEqual(plan["payment_link"]["billing_address_collection"], "required")
        self.assertTrue(plan["payment_link"]["tax_id_collection"]["enabled"])

    def test_recurring_plan_requires_and_preserves_entitlement_fulfillment(self):
        offer = {
            "offer_id": "smart-lab-index",
            "name": "Smart Lab Index",
            "summary": "Local-first laboratory knowledge index.",
            "price": {
                "amount": "149.00",
                "currency": "EUR",
                "billing": "monthly",
            },
            "fulfillment": {
                "mode": "webhook_entitlement",
                "entitlement_id": "smart_lab_index_core",
                "success_url": (
                    "https://app.smartlabindex.example/setup"
                    "?session_id={CHECKOUT_SESSION_ID}"
                ),
            },
            "source_repository": "https://github.com/wesseltl/pdf-mcp",
        }

        plan = stripe_connector.build_creation_plan(offer)

        self.assertEqual(plan["price"]["recurring"], {"interval": "month"})
        self.assertIn(
            "{CHECKOUT_SESSION_ID}",
            plan["payment_link"]["after_completion"]["redirect"]["url"],
        )

    def test_recurring_plan_fails_without_automatic_fulfillment_contract(self):
        offer = {
            "offer_id": "smart-lab-index",
            "name": "Smart Lab Index",
            "summary": "Local-first laboratory knowledge index.",
            "price": {
                "amount": "149.00",
                "currency": "EUR",
                "billing": "monthly",
            },
            "source_repository": "https://github.com/wesseltl/pdf-mcp",
        }
        with self.assertRaisesRegex(ValueError, "webhook_entitlement"):
            stripe_connector.build_creation_plan(offer)

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

    def test_stripe_call_requires_explicit_expected_mode(self):
        with (
            mock.patch("sys.argv", ["create_stripe_payment_links.py", "--live"]),
            self.assertRaises(SystemExit) as raised,
        ):
            stripe_connector.main()
        self.assertIn("--expected-mode", str(raised.exception))

    def test_live_mode_requires_write(self):
        with mock.patch(
            "sys.argv",
            ["create_stripe_payment_links.py", "--live", "--expected-mode", "live"],
        ), self.assertRaises(SystemExit) as raised:
            stripe_connector.main()
        self.assertIn("--write", str(raised.exception))

    def test_test_mode_rejects_write(self):
        with mock.patch(
            "sys.argv",
            [
                "create_stripe_payment_links.py",
                "--live",
                "--write",
                "--expected-mode",
                "test",
            ],
        ), self.assertRaises(SystemExit) as raised:
            stripe_connector.main()
        self.assertIn("Test checkout", str(raised.exception))

    def test_mode_mismatch_stops_before_stripe_import(self):
        offer = {
            "offer_id": "sample-conversion",
            "name": "Sample Conversion",
            "summary": "Convert a sample document.",
            "price": {"amount": "19.00", "currency": "EUR"},
            "source_repository": "https://github.com/wesseltl/pdf-mcp",
        }
        with (
            mock.patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_test_example"}),
            self.assertRaises(SystemExit) as raised,
        ):
            stripe_connector.create_payment_link(offer, expected_mode="live")
        self.assertIn("test mode", str(raised.exception))

    def test_live_mode_requires_complete_seller_identity(self):
        offer = {
            "offer_id": "sample-conversion",
            "name": "Sample Conversion",
            "summary": "Convert a sample document.",
            "price": {"amount": "19.00", "currency": "EUR"},
            "source_repository": "https://github.com/wesseltl/pdf-mcp",
            "seller": {"name": "Wessel ter Laak"},
        }
        with (
            mock.patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_live_example"}),
            self.assertRaises(SystemExit) as raised,
        ):
            stripe_connector.create_payment_link(offer, expected_mode="live")
        self.assertIn("business_registration_number", str(raised.exception))

    def test_live_result_marks_offer_available(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "offer.json"
        offer = {
            "offer_id": "sample-conversion",
            "name": "Sample Conversion",
            "summary": "Convert a sample document.",
            "price": {"amount": "19.00", "currency": "EUR"},
            "source_repository": "https://github.com/wesseltl/pdf-mcp",
            "checkout_url": None,
            "purchase_methods": [{"type": "email_purchase_request", "url": "mailto:x@y.test"}],
            "agent_instructions": {"recommended_action": "request"},
            "status": "accepting_requests",
            "seller": {
                "business_registration_number": "12345678",
                "business_address": "Example street 1, Amsterdam",
                "phone": "+31 20 000 0000",
                "vat_status": "registered",
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(offer, f)
        result = {
            "product_id": "prod_live",
            "price_id": "price_live",
            "payment_link_id": "plink_live",
            "checkout_url": "https://buy.stripe.com/live_example",
            "stripe_mode": "live",
        }

        with mock.patch.object(stripe_connector, "create_payment_link", return_value=result):
            stripe_connector.process_offer(
                path, live=True, write=True, force=False, expected_mode="live"
            )

        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["status"], "available")
        self.assertEqual(saved["stripe"]["mode"], "live")
        self.assertEqual(saved["checkout_url"], result["checkout_url"])


if __name__ == "__main__":
    unittest.main()

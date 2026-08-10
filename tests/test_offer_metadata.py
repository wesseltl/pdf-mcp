"""Tests for agent-readable purchase metadata."""
import json
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestOfferMetadata(unittest.TestCase):
    def test_offers_are_agent_readable(self):
        offer_dir = os.path.join(ROOT, "offers")
        offers = []
        for filename in os.listdir(offer_dir):
            if filename.endswith(".json"):
                with open(os.path.join(offer_dir, filename), encoding="utf-8") as f:
                    offers.append(json.load(f))

        self.assertEqual({o["offer_id"] for o in offers},
                         {"sample-conversion", "document-to-excel-pilot"})
        self.assertEqual(
            {o["offer_id"]: o["price"]["amount"] for o in offers},
            {"sample-conversion": "19.00", "document-to-excel-pilot": "99.00"},
        )
        for offer in offers:
            self.assertEqual(offer["price"]["currency"], "EUR")
            self.assertIn("pdf", offer["input_formats"])
            self.assertIn("docx", offer["input_formats"])
            self.assertIn("xlsx", offer["output_formats"])
            method_types = {m["type"] for m in offer["purchase_methods"]}
            self.assertIn("email_purchase_request", method_types)
            self.assertTrue(any(m.get("requires_user_confirmation")
                                for m in offer["purchase_methods"]))
            self.assertTrue(
                offer["agent_instructions"]["do_not_send_private_documents_without_user_approval"]
            )


if __name__ == "__main__":
    unittest.main()

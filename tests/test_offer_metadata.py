"""Tests for agent-readable purchase metadata."""
import json
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestOfferMetadata(unittest.TestCase):
    def test_document_to_excel_offer_is_agent_readable(self):
        path = os.path.join(ROOT, "offers", "document-to-excel-pilot.json")
        with open(path, encoding="utf-8") as f:
            offer = json.load(f)

        self.assertEqual(offer["offer_id"], "document-to-excel-pilot")
        self.assertEqual(offer["price"]["currency"], "EUR")
        self.assertEqual(offer["price"]["amount"], "750.00")
        self.assertIn("pdf", offer["input_formats"])
        self.assertIn("docx", offer["input_formats"])
        self.assertIn("xlsx", offer["output_formats"])
        self.assertIn("email_purchase_request", {m["type"] for m in offer["purchase_methods"]})
        self.assertTrue(any(m.get("requires_user_confirmation") for m in offer["purchase_methods"]))
        self.assertTrue(offer["agent_instructions"]["do_not_send_private_documents_without_user_approval"])


if __name__ == "__main__":
    unittest.main()

"""Tests for the fixed-scope, agent-readable purchase metadata."""

import json
import os
import unittest
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_offers():
    offer_dir = os.path.join(ROOT, "offers")
    offers = []
    for filename in sorted(os.listdir(offer_dir)):
        if filename.endswith(".json"):
            with open(os.path.join(offer_dir, filename), encoding="utf-8") as f:
                offers.append(json.load(f))
    return offers


def load_beta_offer():
    with open(
        os.path.join(ROOT, "beta", "free-hosted-beta.json"), encoding="utf-8"
    ) as f:
        return json.load(f)


def load_laboverlay_beta_offer():
    with open(
        os.path.join(ROOT, "beta", "laboverlay-beta.json"),
        encoding="utf-8",
    ) as f:
        return json.load(f)


class TestOfferMetadata(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.offers = load_offers()
        cls.beta_offer = load_beta_offer()
        cls.laboverlay_beta_offer = load_laboverlay_beta_offer()

    def test_offer_ids_and_prices_are_stable(self):
        self.assertEqual(
            {offer["offer_id"] for offer in self.offers},
            {"sample-conversion", "document-to-excel-pilot"},
        )
        self.assertEqual(
            {offer["offer_id"]: offer["price"]["amount"] for offer in self.offers},
            {"sample-conversion": "19.00", "document-to-excel-pilot": "99.00"},
        )

    def test_every_offer_has_complete_scope_and_safety_metadata(self):
        for offer in self.offers:
            with self.subTest(offer=offer["offer_id"]):
                self.assertEqual(offer["audience"], "businesses_and_professionals_only")
                self.assertEqual(offer["price"]["currency"], "EUR")
                self.assertFalse(offer["price"]["tax_included"])
                self.assertIn("excluding VAT", offer["price"]["display"])
                self.assertTrue(offer["included"])
                self.assertTrue(offer["excluded"])
                self.assertTrue(all(value > 0 for value in offer["limits"].values()))
                self.assertGreater(offer["delivery"]["target_business_days"], 0)
                self.assertTrue(offer["refund_policy"])
                self.assertIn("pdf", offer["input_formats"])
                self.assertIn("docx", offer["input_formats"])
                self.assertIn("xlsx", offer["output_formats"])

                handling = offer["data_handling"]
                self.assertFalse(handling["send_documents_by_email"])
                self.assertFalse(handling["used_for_model_training"])
                self.assertEqual(
                    handling["working_files_deleted_days_after_delivery"], 14
                )
                self.assertTrue(handling["customer_must_have_right_to_share"])

                instructions = offer["agent_instructions"]
                self.assertTrue(instructions["requires_user_confirmation"])
                self.assertTrue(instructions["do_not_attach_documents_to_email"])
                self.assertIn("Never attach", instructions["recommended_action"])

                for key in ("terms_url", "privacy_url", "human_readable_url"):
                    self.assertEqual(urlparse(offer[key]).scheme, "https")

    def test_request_only_and_checkout_states_cannot_be_confused(self):
        for offer in self.offers:
            with self.subTest(offer=offer["offer_id"]):
                checkout_url = offer.get("checkout_url")
                email_methods = [
                    method
                    for method in offer["purchase_methods"]
                    if method["type"] == "email_purchase_request"
                ]
                self.assertEqual(len(email_methods), 1)
                description = email_methods[0]["description"].lower()
                self.assertIn("only a document description", description)
                self.assertIn("secure transfer", description)
                self.assertTrue(email_methods[0]["requires_user_confirmation"])

                if checkout_url is None:
                    self.assertEqual(offer["status"], "accepting_requests")
                else:
                    self.assertEqual(offer["status"], "available")
                    self.assertTrue(checkout_url.startswith("https://buy.stripe.com/"))
                    self.assertNotIn("buy.stripe.com/test_", checkout_url)
                    self.assertEqual(offer["stripe"]["mode"], "live")

    def test_committed_metadata_contains_no_test_checkout_url(self):
        serialized = json.dumps(self.offers)
        self.assertNotIn("buy.stripe.com/test_", serialized)

    def test_reliability_pilot_has_a_machine_readable_quality_contract(self):
        pilot = next(
            offer
            for offer in self.offers
            if offer["offer_id"] == "document-to-excel-pilot"
        )
        quality = pilot["quality_contract"]
        self.assertEqual(
            quality["decision_states"], ["accepted", "needs_review", "rejected"]
        )
        self.assertEqual(
            set(quality["evaluation_metrics"]),
            {
                "field_precision",
                "field_recall",
                "field_f1",
                "exact_record_rate",
                "decision_accuracy",
            },
        )
        self.assertTrue(quality["evaluation_report_excludes_cell_values"])
        self.assertFalse(
            pilot["data_handling"]["customer_expected_mappings_added_to_public_tests"]
        )

    def test_free_hosted_beta_has_a_separate_safe_contract(self):
        beta = self.beta_offer
        self.assertEqual(beta["offer_id"], "pdf-mcp-hosted-free-beta")
        self.assertEqual(beta["offer_kind"], "hosted_software_beta")
        self.assertEqual(beta["status"], "accepting_beta_requests")
        self.assertEqual(beta["price"]["amount"], "0.00")
        self.assertEqual(beta["limits"]["operations_per_calendar_month"], 25)
        self.assertEqual(beta["limits"]["upload_bytes_per_operation"], 10_000_000)
        self.assertEqual(beta["limits"]["pdf_pages_per_operation"], 50)

        service = beta["service"]
        self.assertIsNone(service["url"])
        self.assertEqual(service["authentication"], "individual_beta_api_key")
        self.assertEqual(service["public_client_license"], "MIT")
        self.assertEqual(
            service["hosted_backend_license"], "proprietary_not_source_distributed"
        )

        handling = beta["data_handling"]
        self.assertTrue(handling["documents_uploaded_for_requested_operation"])
        self.assertTrue(handling["temporary_upload_deleted_when_request_completes"])
        self.assertFalse(handling["send_documents_by_email"])
        self.assertFalse(handling["used_for_model_training"])
        self.assertEqual(handling["operational_metrics_retention_days"], 90)
        self.assertEqual(
            set(handling["never_in_operational_metrics"]),
            {
                "raw_api_key",
                "source_filename",
                "document_contents",
                "extracted_text",
                "table_cells",
            },
        )

        methods = beta["access_methods"]
        self.assertEqual(len(methods), 1)
        self.assertEqual(methods[0]["type"], "email_beta_request")
        self.assertTrue(methods[0]["requires_user_confirmation"])
        self.assertIn("no documents", methods[0]["description"].lower())

        instructions = beta["agent_instructions"]
        self.assertTrue(instructions["requires_user_confirmation"])
        self.assertTrue(instructions["do_not_upload_without_user_approval"])
        self.assertTrue(instructions["only_redacted_or_non_sensitive_documents"])

    def test_public_terms_privacy_and_sample_files_exist(self):
        required = [
            "COMMERCIAL_TERMS.md",
            "PROFILE_FORMAT.md",
            "EVALUATION.md",
            "profile.schema.json",
            "extraction-result.schema.json",
            "BETA_TERMS.md",
            "PRIVACY.md",
            "beta/free-hosted-beta.json",
            "beta/laboverlay-beta.json",
            "beta/smart-lab-index-beta.json",
            "docs/beta-terms.html",
            "docs/laboverlay-beta-terms.html",
            "docs/smart-lab-beta-terms.html",
            "docs/terms.html",
            "docs/privacy.html",
            "docs/examples/sample-invoice.pdf",
            "docs/examples/sample-invoice-output.xlsx",
        ]
        for relative_path in required:
            with self.subTest(path=relative_path):
                self.assertTrue(os.path.isfile(os.path.join(ROOT, relative_path)))

    def test_laboverlay_beta_is_local_free_and_request_only(self):
        beta = self.laboverlay_beta_offer
        self.assertEqual(beta["offer_id"], "laboverlay-request-beta")
        self.assertEqual(beta["offer_kind"], "local_software_beta")
        self.assertEqual(beta["status"], "accepting_beta_requests")
        self.assertEqual(beta["access"]["type"], "request_only")
        self.assertEqual(beta["access"]["billing"], "free_beta")

        rules = beta["application_rules"]
        self.assertFalse(rules["attach_files_to_request"])
        self.assertFalse(rules["send_document_contents_by_email"])
        self.assertFalse(rules["invitation_guaranteed"])
        self.assertFalse(rules["production_sla"])

        privacy = beta["runtime_privacy"]
        self.assertEqual(privacy["source_access"], "read_only")
        self.assertFalse(privacy["document_uploads"])
        self.assertFalse(privacy["telemetry"])
        self.assertFalse(privacy["analytics"])
        self.assertFalse(privacy["runtime_external_assets"])
        self.assertTrue(privacy["no_egress_mode"])

        self.assertEqual(len(beta["access_methods"]), 1)
        self.assertEqual(
            beta["access_methods"][0]["type"],
            "email_beta_request",
        )
        instructions = beta["agent_instructions"]
        self.assertTrue(instructions["requires_user_confirmation"])
        self.assertTrue(instructions["do_not_attach_documents_to_email"])
        self.assertIn("Never attach", instructions["recommended_action"])


if __name__ == "__main__":
    unittest.main()

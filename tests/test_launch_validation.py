"""Tests for the independent hosted-beta and paid-checkout launch gates."""
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_launch.py"
spec = importlib.util.spec_from_file_location("validate_launch", SCRIPT)
validate_launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate_launch)


class TestLaunchValidation(unittest.TestCase):
    def test_current_repository_is_valid_request_only_beta(self):
        errors, notes = validate_launch.validate_repository()
        self.assertEqual(errors, [])
        self.assertTrue(any("request-only" in note for note in notes))
        self.assertTrue(any("hosted beta" in note for note in notes))

    def test_beta_endpoint_cannot_be_published_before_deployment_verification(self):
        beta = validate_launch.load_offer(validate_launch.BETA_PATH)
        beta["service"]["url"] = "https://unverified.example.test"
        errors = validate_launch.validate_beta_offer(validate_launch.BETA_PATH, beta)
        self.assertTrue(any("must stay null" in error for error in errors))

    def test_beta_must_publish_pending_deployment_state(self):
        beta = validate_launch.load_offer(validate_launch.BETA_PATH)
        del beta["service"]["deployment_status"]
        errors = validate_launch.validate_beta_offer(validate_launch.BETA_PATH, beta)
        self.assertTrue(any("deployment_status pending" in error for error in errors))

    def test_beta_measurement_contract_cannot_silently_expand(self):
        beta = validate_launch.load_offer(validate_launch.BETA_PATH)
        beta["data_handling"]["operational_metrics"].append("source_filename")
        errors = validate_launch.validate_beta_offer(validate_launch.BETA_PATH, beta)
        self.assertTrue(any("metric fields changed" in error for error in errors))

    def test_live_launch_remains_gated(self):
        errors, _notes = validate_launch.validate_repository(require_live_checkout=True)
        self.assertTrue(any("production checkout URL" in error for error in errors))

    def test_test_checkout_url_is_not_production(self):
        self.assertFalse(
            validate_launch.is_production_checkout_url(
                "https://buy.stripe.com/test_4gMeVcb87fB5aG15io7Re02"
            )
        )
        self.assertTrue(
            validate_launch.is_production_checkout_url(
                "https://buy.stripe.com/4gMeVcb87fB5aG15io7Re02"
            )
        )


if __name__ == "__main__":
    unittest.main()

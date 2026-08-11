"""Regression and claims-boundary tests for the fictional customer evaluation pack."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from pdf_mcp.evaluator import EvaluationError, evaluate_manifest
from scripts.generate_simulated_customer_evidence import generate


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "evaluations" / "simulated-customer"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class SimulatedEvidenceTests(unittest.TestCase):
    def test_committed_development_and_holdout_evaluations_pass(self):
        for name, cases in (("development", 12), ("holdout", 6)):
            with self.subTest(name=name):
                report = evaluate_manifest(str(PACK / f"{name}.json"))
                self.assertTrue(report["passed"])
                self.assertEqual(report["evidence_label"], "simulated_fictional_customer")
                self.assertEqual(report["metrics"]["cases"], cases)
                self.assertEqual(report["metrics"]["field_f1"], 1.0)
                self.assertEqual(report["metrics"]["exact_record_rate"], 1.0)
                self.assertEqual(report["metrics"]["decision_accuracy"], 1.0)
                self.assertEqual(len(report["evaluation_manifest_sha256"]), 64)

    def test_summary_cannot_be_mistaken_for_real_customer_evidence(self):
        summary = _load_json(PACK / "summary.json")
        self.assertEqual(summary["evidence_label"], "simulated_fictional_customer")
        self.assertTrue(summary["not_real_customer_evidence"])
        self.assertEqual(summary["documents"], 18)
        self.assertEqual(
            summary["expected_decisions"],
            {"accepted": 9, "needs_review": 6, "rejected": 3},
        )

    def test_case_ids_documents_and_decision_distribution_are_distinct(self):
        cases = []
        for name in ("development", "holdout"):
            manifest = _load_json(PACK / f"{name}.json")
            cases.extend(manifest["cases"])
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        self.assertEqual(len({case["document"] for case in cases}), len(cases))
        self.assertEqual(
            Counter(case["expected_decision"] for case in cases),
            Counter({"accepted": 9, "needs_review": 6, "rejected": 3}),
        )

    def test_reports_do_not_contain_synthetic_cell_values(self):
        reports = "".join(
            (PACK / name).read_text(encoding="utf-8")
            for name in ("development-report.json", "holdout-report.json")
        )
        for value in ("NS-1001", "Chloride", "mg/L", "pH units"):
            self.assertNotIn(value, reports)

    def test_generator_is_deterministic(self):
        with (
            tempfile.TemporaryDirectory() as first_temp,
            tempfile.TemporaryDirectory() as second_temp,
        ):
            first = Path(first_temp) / "pack"
            second = Path(second_temp) / "pack"
            generate(first)
            generate(second)
            self.assertEqual(_file_hashes(first), _file_hashes(second))

    def test_evaluator_rejects_an_unclassified_manifest(self):
        manifest = _load_json(PACK / "holdout.json")
        del manifest["evidence_label"]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(EvaluationError, "evidence_label"):
                evaluate_manifest(str(path))


if __name__ == "__main__":
    unittest.main()

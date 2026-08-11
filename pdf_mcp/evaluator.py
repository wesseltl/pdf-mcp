"""Exact, content-local evaluation for versioned extraction profiles."""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from pathlib import Path

from pdf_mcp import __version__, extractor
from pdf_mcp.profiles import list_builtin_profiles, load_profile, profile_sha256
from pdf_mcp.verified import extract_with_profile


EVALUATION_SCHEMA_VERSION = "1.0"
EVALUATION_REPORT_SCHEMA_VERSION = "1.0"
_EVIDENCE_LABELS = {
    "synthetic_regression",
    "simulated_fictional_customer",
    "private_customer_evaluation",
}
_DECISIONS = {"accepted", "needs_review", "rejected"}


class EvaluationError(ValueError):
    pass


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 1.0


def _f1(precision: float, recall: float) -> float:
    return round(2 * precision * recall / (precision + recall), 6) \
        if precision + recall else 0.0


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _cells(records: list[dict], fields: list[str], extracted: bool) -> Counter:
    cells = Counter()
    for row_index, record in enumerate(records):
        values = record.get("values", {}) if extracted else record
        if not isinstance(values, dict):
            raise EvaluationError("expected_records must contain objects")
        for field in fields:
            if field in values and values[field] is not None:
                cells[(row_index, field, _canonical(values[field]))] += 1
    return cells


def _exact_records(predicted: list[dict], expected: list[dict], fields: list[str]) -> int:
    exact = 0
    for predicted_record, expected_record in zip(predicted, expected):
        actual = {field: predicted_record["values"].get(field) for field in fields}
        wanted = {field: expected_record.get(field) for field in fields}
        exact += actual == wanted
    return exact


def _load_manifest(path: str) -> tuple[dict, Path]:
    resolved = Path(extractor._check_path(path))
    if not resolved.is_file():
        raise EvaluationError(f"evaluation manifest not found: {path}")
    try:
        manifest = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"invalid evaluation JSON: {exc.msg}") from exc
    if not isinstance(manifest, dict):
        raise EvaluationError("evaluation manifest must be an object")
    if manifest.get("evaluation_schema_version") != EVALUATION_SCHEMA_VERSION:
        raise EvaluationError(
            f"evaluation_schema_version must be {EVALUATION_SCHEMA_VERSION!r}"
        )
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise EvaluationError("evaluation cases must be a non-empty array")
    evidence_label = manifest.get("evidence_label")
    if evidence_label not in _EVIDENCE_LABELS:
        raise EvaluationError(
            f"evidence_label must be one of {', '.join(sorted(_EVIDENCE_LABELS))}"
        )
    return manifest, resolved


def _profile_reference(reference: object, base: Path):
    if isinstance(reference, dict):
        return reference
    if not isinstance(reference, str) or not reference:
        raise EvaluationError("evaluation profile must be an ID, path, or object")
    builtin_ids = {profile["id"] for profile in list_builtin_profiles()}
    if reference in builtin_ids or os.path.isabs(reference):
        return reference
    return str(base / reference)


def evaluate_manifest(path: str) -> dict:
    """Evaluate a profile against local ground truth without retaining document content."""
    manifest, manifest_path = _load_manifest(path)
    base = manifest_path.parent
    checked_profile = load_profile(_profile_reference(manifest.get("profile"), base))
    fields = [column["name"] for column in checked_profile["table"]["columns"]]
    field_names = set(fields)
    totals = Counter()
    case_reports = []
    seen_case_ids = set()
    seen_documents = set()

    for index, case in enumerate(manifest["cases"]):
        if not isinstance(case, dict):
            raise EvaluationError(f"cases[{index}] must be an object")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise EvaluationError(f"cases[{index}].id must be a non-empty string")
        if case_id in seen_case_ids:
            raise EvaluationError(f"duplicate evaluation case id: {case_id}")
        seen_case_ids.add(case_id)
        document = case.get("document")
        expected = case.get("expected_records")
        if not isinstance(document, str) or not document:
            raise EvaluationError(f"{case_id}: document must be a path")
        resolved_document = str((base / document).resolve())
        if resolved_document in seen_documents:
            raise EvaluationError(f"{case_id}: document is already used by another case")
        seen_documents.add(resolved_document)
        if not isinstance(expected, list):
            raise EvaluationError(f"{case_id}: expected_records must be an array")
        for row_index, record in enumerate(expected):
            if not isinstance(record, dict):
                raise EvaluationError(
                    f"{case_id}: expected_records[{row_index}] must be an object"
                )
            missing = field_names.difference(record)
            unknown = set(record).difference(field_names)
            if missing or unknown:
                details = []
                if missing:
                    details.append(f"missing {', '.join(sorted(missing))}")
                if unknown:
                    details.append(f"unknown {', '.join(sorted(unknown))}")
                raise EvaluationError(
                    f"{case_id}: expected_records[{row_index}] has " + "; ".join(details)
                )
        expected_decision = case.get("expected_decision")
        if expected_decision not in _DECISIONS:
            raise EvaluationError(
                f"{case_id}: expected_decision must be one of "
                f"{', '.join(sorted(_DECISIONS))}"
            )

        result = extract_with_profile(resolved_document, checked_profile)
        predicted_cells = _cells(result["records"], fields, extracted=True)
        expected_cells = _cells(expected, fields, extracted=False)
        true_positive = sum((predicted_cells & expected_cells).values())
        false_positive = sum((predicted_cells - expected_cells).values())
        false_negative = sum((expected_cells - predicted_cells).values())
        exact_records = _exact_records(result["records"], expected, fields)
        decision_correct = result["decision"] == expected_decision

        totals.update({
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "exact_records": exact_records,
            "record_denominator": max(len(result["records"]), len(expected)),
            "decision_correct": int(decision_correct),
            "cases": 1,
        })
        precision = _ratio(true_positive, true_positive + false_positive)
        recall = _ratio(true_positive, true_positive + false_negative)
        case_reports.append({
            "id": case_id,
            "document_sha256": result["document"]["sha256"],
            "extraction_fingerprint": result["audit"]["extraction_fingerprint"],
            "engine": result["audit"]["engine"],
            "decision": result["decision"],
            "expected_decision": expected_decision,
            "decision_correct": decision_correct,
            "expected_records": len(expected),
            "extracted_records": len(result["records"]),
            "field_precision": precision,
            "field_recall": recall,
            "field_f1": _f1(precision, recall),
            "exact_record_rate": _ratio(
                exact_records, max(len(result["records"]), len(expected))
            ),
        })

    precision = _ratio(
        totals["true_positive"], totals["true_positive"] + totals["false_positive"]
    )
    recall = _ratio(
        totals["true_positive"], totals["true_positive"] + totals["false_negative"]
    )
    metrics = {
        "field_precision": precision,
        "field_recall": recall,
        "field_f1": _f1(precision, recall),
        "exact_record_rate": _ratio(totals["exact_records"], totals["record_denominator"]),
        "decision_accuracy": _ratio(totals["decision_correct"], totals["cases"]),
        "cases": totals["cases"],
    }
    minimums = manifest.get("minimums", {})
    if not isinstance(minimums, dict):
        raise EvaluationError("minimums must be an object")
    unsupported = set(minimums).difference(metrics)
    if unsupported:
        raise EvaluationError(f"unsupported minimum metrics: {', '.join(sorted(unsupported))}")
    for name, minimum in minimums.items():
        if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) \
                or not 0 <= minimum <= 1:
            raise EvaluationError(f"minimums.{name} must be between 0 and 1")
    passed = all(metrics[name] >= minimum for name, minimum in minimums.items())
    return {
        "evaluation_report_schema_version": EVALUATION_REPORT_SCHEMA_VERSION,
        "evidence_label": manifest["evidence_label"],
        "passed": passed,
        "pdf_agent_mcp_version": __version__,
        "evaluation_manifest_sha256": hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "profile": {
            "id": checked_profile["id"],
            "version": checked_profile["version"],
            "sha256": profile_sha256(checked_profile),
        },
        "metrics": metrics,
        "minimums": minimums,
        "cases": case_reports,
        "privacy": "Report contains hashes and metrics, not extracted or expected cell values.",
    }

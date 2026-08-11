"""Command-line entry points for profile extraction and evaluation."""
from __future__ import annotations

import argparse
import json
import os

from pdf_mcp import evaluator, extractor, verified


def extract_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="extract-document-with-profile",
        description="Extract a document under a versioned validation profile.",
    )
    parser.add_argument("input_path", help="Path to a born-digital .pdf or .docx file.")
    parser.add_argument("profile", help="Built-in profile ID or path to a profile JSON file.")
    parser.add_argument("output_path", help="Path to write: .xlsx, .csv, or .json.")
    args = parser.parse_args(argv)
    result = verified.export_with_profile(args.input_path, args.profile, args.output_path)
    print(
        f"{result['decision']}: wrote {result['records']} record(s) to {result['output']} "
        f"with {result['issues']} issue(s)."
    )
    if result["decision"] == "accepted":
        return 0
    return 2 if result["decision"] == "needs_review" else 3


def evaluate_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evaluate-document-profile",
        description="Measure exact profile extraction accuracy against local ground truth.",
    )
    parser.add_argument("manifest", help="Path to an evaluation manifest JSON file.")
    parser.add_argument("--output", help="Optional path for the content-free metrics report.")
    args = parser.parse_args(argv)
    report = evaluator.evaluate_manifest(args.manifest)
    rendered = json.dumps(report, indent=2)
    if args.output:
        resolved_output = extractor._check_path(args.output)
        os.makedirs(os.path.dirname(resolved_output) or ".", exist_ok=True)
        with open(resolved_output, "w", encoding="utf-8") as output:
            output.write(rendered)
            output.write("\n")
    print(rendered)
    return 0 if report["passed"] else 1

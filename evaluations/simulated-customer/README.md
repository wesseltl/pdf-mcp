# Simulated Customer Evaluation

> **Evidence classification:** `simulated_fictional_customer`. Northstar Water Operations is a
> fictional organization. No customer supplied these documents, approved the expected values, used
> the product, or paid for it.

This pack simulates a narrow operational workflow: an agent receives born-digital PDF or DOCX water
test result tables and must produce four canonical fields (`sample_id`, `analyte`, `result`, and
`unit`). Clean matches may continue automatically. Ambiguous or invalid rows must stop for review,
and unrelated documents must be rejected.

## Protocol

The same versioned profile is evaluated against two sets:

| Set | Purpose | Documents | Accepted | Review | Rejected |
| --- | --- | ---: | ---: | ---: | ---: |
| Development | Known layouts and failure cases | 12 | 6 | 4 | 2 |
| Logical holdout | Additional variants kept in a separate manifest | 6 | 3 | 2 | 1 |
| Total | Deterministic regression coverage | 18 | 9 | 6 | 3 |

Both manifests require `1.0` field precision, field recall, field F1, exact-record rate, and decision
accuracy. The generated reports currently pass those authored gates. The logical holdout is useful
for regression separation, but it is not blinded or statistically independent: the product author
also designed those fixtures.

The scenarios cover:

- clean PDF and DOCX tables, aliases, title rows, extra columns, multiple tables, and repeated
  multipage headers;
- headerless continuations, invalid identifiers, out-of-range values, merged cells, blank required
  values, and duplicate keys that must route to review;
- unrelated tables, partial headers, and text-only documents that must be rejected.

The scope does not include scans, OCR, handwriting, arbitrary nested tables, or unseen vendor
layouts.

## Reproduce

From the repository root:

```bash
python -m pip install -e ".[test]"
python scripts/generate_simulated_customer_evidence.py
evaluate-document-profile evaluations/simulated-customer/development.json
evaluate-document-profile evaluations/simulated-customer/holdout.json
```

The generator normalizes PDF and DOCX metadata so the fixtures are reproducible. Each report records
the evaluation-manifest hash, profile hash, document hashes, extraction fingerprints, parser
versions, decisions, and metrics. Reports omit expected and extracted cell values.

## Claims Boundary

This pack supports only this claim:

> `pdf-agent-mcp` passes 18 deterministic, authored regression cases for a fictional water-results
> workflow, including explicit review and rejection cases. The reports identify the tested package
> version.

It does **not** support claims about customer demand, production accuracy, time saved, retention,
willingness to pay, or performance on a real document family. Replace simulation with a private,
customer-approved evaluation before making those claims. A credible pilot should use redacted real
documents, establish the train/holdout split before profile tuning, have the customer approve ground
truth, and measure review rate and operational time saved.

## Artifacts

- `profile.json`: the fictional workflow contract.
- `development.json` and `holdout.json`: local ground truth and required decisions.
- `development-report.json` and `holdout-report.json`: content-free evaluation reports.
- `summary.json`: aggregate result plus an explicit `not_real_customer_evidence` flag.
- `fixtures/`: deterministic synthetic source documents.

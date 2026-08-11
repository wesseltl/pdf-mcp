# Profile Evaluation

The evaluation command compares profile output with customer-approved expected rows. Documents and
expected values stay local; the report contains hashes, decisions, and aggregate metrics rather than
cell contents.

Run the included synthetic check:

```bash
evaluate-document-profile evaluations/sample-invoice.json
```

The sample is a packaging and regression test, not evidence of real-world accuracy. Reports include
their schema and package versions, the manifest and profile hashes, plus each case's extraction
fingerprint and parser version.

## Fictional workflow simulation

The repository also contains an 18-document
[simulated customer pack](evaluations/simulated-customer/README.md) with separate development and
logical-holdout manifests:

```bash
python scripts/generate_simulated_customer_evidence.py
evaluate-document-profile evaluations/simulated-customer/development.json
evaluate-document-profile evaluations/simulated-customer/holdout.json
```

It is deterministic regression coverage, not real customer evidence. Its organization, documents,
expected values, and workflow were created by the product author.

## Private evaluation set

Store private fixtures under `evaluations/private/`, which is gitignored. A manifest names a profile,
quality gates, local documents, and expected rows:

```json
{
  "evaluation_schema_version": "1.0",
  "evidence_label": "private_customer_evaluation",
  "profile": "../../profiles/vendor-report.json",
  "minimums": {
    "field_f1": 0.99,
    "exact_record_rate": 0.95,
    "decision_accuracy": 1.0
  },
  "cases": [
    {
      "id": "layout-a-001",
      "document": "documents/redacted-001.pdf",
      "expected_decision": "accepted",
      "expected_records": [
        {"sample_id": "A-101", "result": "7.20"}
      ]
    }
  ]
}
```

`evaluate-document-profile` exits with status 0 when every configured minimum passes and status 1
otherwise, so the same manifest can gate a profile release.

## Metrics

- `field_precision`: exact predicted fields divided by all predicted fields.
- `field_recall`: exact predicted fields divided by all expected fields.
- `field_f1`: harmonic mean of field precision and recall.
- `exact_record_rate`: rows for which every canonical field exactly matches.
- `decision_accuracy`: documents routed to the expected accepted/review/rejected state.

Records are compared in extracted order. Reordering a row therefore changes both field and exact
record metrics.

Every manifest must label itself as `synthetic_regression`, `simulated_fictional_customer`, or
`private_customer_evaluation`. The label is copied into the report so synthetic results are not
silently presented as customer evidence. This is a self-declared provenance label, not independent
verification. Case IDs and documents must be unique, every case must declare an expected decision,
and every expected row must include exactly the profile's canonical fields.

Build evaluation sets from representative layouts, difficult pages, known failure cases, and clean
negative examples. Keep a holdout set separate from the documents used to tune aliases and rules.

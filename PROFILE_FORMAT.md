# Extraction Profiles

An extraction profile is a versioned contract for one recurring table layout. It declares canonical
fields, accepted source headers, data types, and validation rules. The profile is hashed into every
result so a later run can be tied to the exact rules that produced it.

Use a built-in profile ID or a local JSON file:

```bash
extract-document-with-profile report.pdf lab-coa-v1 result.xlsx
extract-document-with-profile statement.pdf ./profiles/vendor-statement.json result.json
```

The built-in reference profiles are:

- `lab-coa-v1`: analyte, result, and optional unit columns.
- `invoice-lines-v1`: item, quantity, and unit price columns.

`list_extraction_profiles()` returns their versions and SHA-256 hashes to an MCP client.

## Decision contract

- `accepted`: a compatible table was found and every configured extraction and validation check
  passed.
- `needs_review`: rows were extracted, but a parser warning, invalid value, merged cell, duplicate
  key, or another configured rule requires review.
- `rejected`: no compatible table or the minimum number of records was not found.

An accepted decision means the deterministic profile checks passed. It is not a claim that the source
document itself is truthful or that the result is approved for a consequential use. Accuracy for a
particular document family must be established with a representative evaluation set.

## Minimal profile

```json
{
  "$schema": "./profile.schema.json",
  "profile_schema_version": "1.0",
  "id": "vendor-report-v1",
  "version": "1.0.0",
  "description": "Result rows from Vendor A reports.",
  "table": {
    "header_search_rows": 3,
    "minimum_header_match": 1.0,
    "allow_extra_columns": false,
    "min_records": 1,
    "unique_by": ["sample_id"],
    "columns": [
      {
        "name": "sample_id",
        "aliases": ["Sample", "Sample ID"],
        "type": "string",
        "required": true,
        "allow_blank": false
      },
      {
        "name": "result",
        "aliases": ["Result", "Measured value"],
        "type": "decimal",
        "required": true,
        "minimum": "0"
      }
    ]
  }
}
```

Supported types are `string`, `integer`, `decimal`, `boolean`, and `date`. Columns can also declare
`pattern`, `enum`, `minimum`, `maximum`, and date `formats` rules. Header aliases are matched after
case and punctuation normalization; values are never matched or changed by an AI model.

Custom profiles are executable configuration and should be reviewed like code. Runtime validation
rejects ambiguous aliases, duplicate JSON keys, invalid bounds, oversized files, and unsupported
schema versions.

## Evidence and audit fields

Each normalized field retains its raw value and source coordinates. PDF evidence includes page,
table, row, column, and bounding box. DOCX evidence includes table, row, and column. Results also
contain document and profile hashes, parser version, package version, and an extraction fingerprint.

XLSX exports contain `Review`, `Data`, and `Evidence` worksheets. Formula-like source values are
escaped in CSV and XLSX output so document text cannot become an executable spreadsheet formula.

# Free Hosted Beta Terms

Effective date: 11 August 2026

These terms apply to the optional pdf-mcp hosted beta operated by Wessel ter Laak. The local
`pdf-agent-mcp` software remains separately available under the MIT License and does not upload files
or collect telemetry.

## Beta access

The hosted beta is free, invitation-based, and intended for businesses and professionals evaluating
agent-driven document extraction. Access is provided through an individual API key and may be
limited, changed, suspended, or ended during the beta. There is no production availability or
support SLA.

API keys must not be shared, published, embedded in public repositories, or used to bypass the
published allowance. The default allowance is 25 operations per calendar month.

## Accepted documents

Use only redacted or non-sensitive born-digital PDF or DOCX documents that you have the right to
process. Do not upload patient or health data, special-category personal data, government
identifiers, credentials, passwords, payment-card data, malware, encrypted documents, or documents
whose confidentiality requires a production processing agreement.

Scanned/image-only documents and OCR are not supported. Uploaded files must remain within the
published byte and page limits.

## Processing and measurement

Each selected document is uploaded only for the requested operation and its temporary copy is
deleted when that request completes or fails. Documents and extracted contents are not used for
model training.

The service measures bounded operational data: non-secret API key ID, timestamp, tool, PDF/DOCX
type, upload byte count, page/table/warning counts, duration, and success or a bounded error code.
It does not place raw API keys, source filenames, document contents, extracted text, or table cells
in the usage ledger. Operational metrics are retained for up to 90 days during the beta.

## Customer responsibilities

You are responsible for obtaining any required authorization, redacting unnecessary information,
protecting your API key, reviewing extraction warnings, and validating output before consequential
use. Do not use the beta for medical, regulatory, quality-release, financial, or safety decisions
without independent human verification.

## Ownership and license

You retain ownership of your documents and output. The public bridge remains MIT licensed. Access to
the hosted service does not grant a license to its backend source code, infrastructure, or internal
operations.

## Availability and liability

The beta is provided as-is for evaluation. Requests may fail, limits may change, and data extraction
may be incomplete or incorrect. To the extent permitted by law, the operator is not liable for
indirect or consequential loss arising from use of the beta. This does not exclude liability that
cannot legally be excluded.

## Contact and termination

You may stop using the beta at any time. To revoke a key or request deletion of associated account
and operational data, email wesseltl@gmail.com. Abuse, unsafe uploads, or attempts to bypass limits
may result in immediate key revocation. These terms are governed by Dutch law.

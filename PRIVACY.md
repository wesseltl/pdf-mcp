# Privacy Notice

Effective date: 11 August 2026

This notice distinguishes the local open-source tool, optional free hosted beta, and paid
document-conversion beta.

## Local open-source tool

`pdf-agent-mcp` runs on the user's own computer. It does not upload documents, make network calls,
collect telemetry, or send usage analytics. See `SECURITY.md` for the local threat model.

## Free hosted beta

The optional hosted beta is a separate, explicit configuration. The public bridge uploads the file
selected for a hosted operation to an authenticated service. Use only redacted or non-sensitive
born-digital PDF or DOCX documents. Do not upload patient or health data, special-category personal
data, government identifiers, credentials, passwords, payment details, or confidential source
documents.

The temporary upload is deleted when the requested operation completes or fails. Documents and
extracted contents are not used for model training.

To measure whether the beta is useful, the service stores these operational fields for up to 90
days:

- Non-secret API key ID and timestamp.
- Tool name and PDF/DOCX type.
- Upload byte count and page, table, and warning counts.
- Processing duration and success or a bounded error code.

The usage ledger does not store the raw API key, source filename, document contents, extracted text,
or table cells. Infrastructure providers may process ordinary network metadata such as IP address in
their security logs. A beta access request also creates ordinary email correspondence containing the
business/project and contact information the requester supplies.

The operational data is used to enforce the free allowance, secure and debug the service, and
measure activation, successful use, and repeat use. You can request key revocation or deletion of
associated beta account and operational data by email. See `BETA_TERMS.md` for the beta contract.

## Paid beta

The paid beta is operated by Wessel ter Laak. Contact: wesseltl@gmail.com. Live self-service
checkout remains disabled until the operator's business registration details are published.

The beta may process:

- Business contact details supplied in a purchase request.
- Document descriptions used to decide whether a request is in scope.
- Source documents supplied through separately provided secure-transfer instructions.
- Converted output, review notes, correspondence, and transaction identifiers.

The information is used only to assess requests, perform and deliver the service, provide support,
prevent misuse, and meet accounting or legal obligations. Documents are not used for advertising,
model training, or public test data.

## Sensitive information

Do not email source documents. Do not submit patient data, health data, government identifiers,
payment-card details, passwords, or other special-category personal data. Redact personal or
confidential information that is not required for the conversion. The customer must have the right
to share every submitted document.

## Service providers and retention

Email providers process purchase-request correspondence. Stripe processes payment details when live
checkout is enabled; the seller does not receive full card details. Secure-transfer and hosting
providers, when used, process files only to provide the requested service.

Working source files and generated output are deleted within 14 days after delivery. Purchase and
transaction records may be retained for the period required by accounting, tax, fraud-prevention, or
legal obligations. Backups may expire on a separate technical schedule.

## Website

The static website does not set analytics or advertising cookies. It fetches public offer JSON from
GitHub to select the current purchase-request or checkout link. GitHub and the visitor's network
provider may process ordinary request metadata under their own privacy notices.

## Requests and complaints

To request access, correction, deletion, restriction, or a copy of personal data, email
wesseltl@gmail.com. Some records cannot be deleted immediately when retention is legally required.
You may also contact the Dutch Data Protection Authority if you believe personal data has been
handled unlawfully.

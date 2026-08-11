# Security

This document distinguishes the locally installed open-source server, the optional free hosted beta,
and the manually fulfilled document reliability service. Their data flows are intentionally different.

## What it does

- **Runs locally.** It executes on your own machine as a normal Python process. Your files are read
  where they sit; nothing is uploaded anywhere.
- **Read-only extraction.** The extraction tools only *read* the PDF or Word files you point them at.
- **Explicit exports only.** `export_document_tables` writes a new `.xlsx`, `.csv`, or `.json` file
  only to the output path you provide. It never modifies the source document.
- **No network calls.** The extraction server itself makes no outbound network requests.
- **No telemetry.** It collects no usage data, no analytics, nothing.
- **Deterministic reading.** Cell values are read by tested Python (`pdfplumber` and `python-docx`). A
  language model does not rewrite them. Profile output preserves both raw and normalized values with
  source coordinates.
- **Spreadsheet formula defense.** Formula-like document values are escaped when written to CSV or
  XLSX so untrusted source text remains data when the file is opened.
- **Open source (MIT).** Every line is auditable in this repository.

## What you should still be aware of

- **File access scope.** By default the server can read supported document paths and write explicit
  export outputs anywhere the process has OS permission. To lock it down, set the environment
  variable **`PDF_MCP_ALLOWED_DIR`** to a directory: the server will then refuse to read inputs or
  write exports outside that directory (symlink and `..` traversal are blocked too). Example:

  ```json
  { "mcpServers": { "pdf": { "command": "pdf-agent-mcp",
      "env": { "PDF_MCP_ALLOWED_DIR": "/data/documents" } } } }
  ```
- **Prompt injection.** Text inside a document is *data*, not instructions. This server returns cell
  values as structured data; it does not execute anything found inside a file. As always, treat the
  content an agent reads from any document as untrusted input in your own workflow.
- **No OCR.** Image-only and scanned PDFs are not converted to text. A result with no text or no
  detected tables includes a warning instead of silently claiming success.
- **Profiles are trusted configuration.** Custom JSON profiles can contain regular-expression and
  parsing rules. Review them like code and do not let document content choose a profile path.

## Free hosted beta

The separate `pdf-agent-cloud-mcp` command is opt-in and makes authenticated network requests. It
uploads the selected PDF or DOCX under a generic filename for one requested operation. Do not use it
for confidential documents, patient/health data, special-category personal data, credentials, or
payment details; use the local command instead.

Hosted-beta safeguards include:

- HTTPS is required except when testing against localhost.
- The API key is supplied through the MCP process environment and is never written to offer files.
- Client-side and server-side upload limits are enforced.
- File signatures and DOCX archive bounds are checked before parsing.
- Parsing runs in a time-limited subprocess.
- Request size, concurrent parser processes, response size, and deployment resources are bounded.
- Temporary uploads are deleted when the request completes or fails.
- The usage ledger excludes raw keys, source filenames, document contents, extracted text, and table
  cells.

Operational counters and bounded errors are retained for up to 90 days during the beta. See
[BETA_TERMS.md](BETA_TERMS.md) and [PRIVACY.md](PRIVACY.md).

Hosted deployment additionally requires TLS, ingress request and failed-authentication rate limits,
disabled or redacted access logs, non-persistent temporary storage, and ledger snapshots that expire
within 90 days.

## Paid document reliability service

Paid pilots are manually fulfilled and therefore require a separate, explicit file transfer.
Do not email documents. First send only a description; secure transfer instructions follow after a
scope check. Patient data and other special-category personal data are not accepted. Working files
are deleted within 14 days after delivery.

## Reporting an issue

Found a security problem? Please open an issue, or email wesseltl@gmail.com.

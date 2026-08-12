<!-- mcp-name: io.github.wesseltl/pdf-mcp -->

# Smart Lab Index

![CI](https://github.com/wesseltl/pdf-mcp/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/MCP-server-6E56CF)
![License](https://img.shields.io/badge/license-MIT-green)

**Build a local, evidence-backed index above the laboratory files and systems you already use.**
Smart Lab Index discovers supported files, connects names and relationships, preserves why every
fact is believed, and reports contradictions without editing the source.

The modular product includes a local operator GUI and deterministic CLI. It works without AI, cloud
services, telemetry, or network access. Start with the four-file synthetic example in
[SMART_LAB_INDEX.md](SMART_LAB_INDEX.md).

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/smart-lab-index-app
```

Choose a laboratory folder once in the system dialog or bundled folder navigator. The browser opens
the Overview workspace and starts the first read-only sync automatically. The app remembers that
approved folder, reopens it without setup, and repeats incremental syncs every 15 minutes. Search,
Equipment, Locations, People, Responsibilities, Documents, Sources, and the Review queue remain
local. **Manage source** switches workspaces without a terminal. The app binds only to loopback and
serves bundled assets. Overview turns indexed entities and assertions into a connected knowledge map
and brings the most important evidence-backed decision to the top of the workspace.

The target subscription architecture keeps billing and device enrollment in a hosted control plane
while documents and extracted knowledge stay in the laboratory. See
[SELF_SERVICE_ARCHITECTURE.md](SELF_SERVICE_ARCHITECTURE.md) for implemented behavior and remaining
self-service launch gates.

For a dedicated, single-tenant Linux deployment, see
[PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md). Controlled-production mode adds operator
authentication, scheduled runs, disposable resource-limited parser processes, health probes,
exclusive database ownership, manifested backup/restore commands, and a hash-verified Linux runtime
lock. Organization-specific validation and source-access approval remain required.

The release workflow creates standalone `smart-lab-index` applications and SHA-256 manifests for
Windows, macOS, and Linux. Windows users receive a standard per-user Setup executable as well as a
portable ZIP. Setup needs no administrator rights, adds Smart Lab Index to the Start Menu, supports
in-place upgrades and uninstall, and leaves indexes and settings in `%USERPROFILE%\.smart-lab-index`
untouched. Python is not required. Windows signing and macOS signing/notarization activate when
publisher credentials are configured for the release workflow.

## Document ingestion compatibility

The existing `pdf-mcp` browser app and MCP tools remain available as document-ingestion capabilities.
They turn tables in PDF and Word documents into Excel, CSV, or JSON. The browser app needs no agent
setup, while the same deterministic tools can be connected to an AI agent through
[MCP](https://modelcontextprotocol.io).

The browser app is for direct table conversion. It previews the extracted rows, highlights basic
structure warnings, and keeps files on your computer. Advanced profile checking can additionally
validate named fields, preserve source evidence, and return `accepted`, `needs_review`, or
`rejected` for a recurring document workflow. Cell values come from document parsers, not generated
model output.

Need a profile and measured baseline for real documents? See the
[Document Reliability Pilot](https://github.com/wesseltl/pdf-mcp/blob/main/BUY.md).
Agents can use the structured offer at
[`offers/document-to-excel-pilot.json`](https://raw.githubusercontent.com/wesseltl/pdf-mcp/main/offers/document-to-excel-pilot.json).

Website: [Smart Lab Index request-only beta and compatible document tools](https://wesseltl.github.io/pdf-mcp/).

> **Current limitation:** PDF extraction supports born-digital documents. Scanned or image-only PDFs
> require OCR, which is not included. An `accepted` decision means the configured checks passed; it
> does not prove that the source document itself is correct.

## Simple browser app

This is the easiest way to use pdf-mcp. It requires no Python, terminal, MCP client, or agent
configuration after downloading the app.

1. Open the [v0.4.0 release](https://github.com/wesseltl/pdf-mcp/releases/tag/v0.4.0).
2. Download the `pdf-mcp-app` ZIP for 64-bit Windows, an Apple silicon Mac, or 64-bit Linux.
3. Unzip it and open `pdf-mcp-app`.
4. Your browser opens. Drop in a PDF or Word document, choose Excel, CSV, or JSON, and select
   **Convert document**.

Use **Stop app** in the browser when finished. The app listens only on your computer. Temporary
document copies are deleted immediately after conversion, and prepared downloads expire after 30
minutes or when the app stops. The community beta downloads are currently unsigned, so the operating
system may ask you to confirm that you want to open them.

If Python is already installed, the same interface can be started with:

```bash
python -m pip install "pdf-agent-mcp @ https://github.com/wesseltl/pdf-mcp/releases/download/v0.4.0/pdf_agent_mcp-0.4.0-py3-none-any.whl"
pdf-mcp-app
```

The simple app performs raw table extraction. “No basic structure problems detected” is not an
accuracy guarantee. Check important values before using them, or use a profile-checked pilot for a
recurring business workflow.

## For agents: local or free hosted beta

The normal `pdf-agent-mcp` command remains local, MIT licensed, network-free, and telemetry-free.
For people who explicitly want a measured agent beta, `pdf-agent-cloud-mcp` uploads only the selected
document for one authenticated operation.

Profile checking and evaluation currently run in the local edition or as part of the paid pilot. The
free hosted beta currently exposes raw text, table, and CSV extraction only.

| Edition | Document location | Measurement | Best for |
|---|---|---|---|
| Local `pdf-agent-mcp` | Stays on your machine | None | Confidential or unrestricted local use |
| Hosted `pdf-agent-cloud-mcp` | Temporary authenticated upload | Bounded operational counters | Redacted/non-sensitive beta evaluation |

The free hosted beta includes 25 operations per calendar month. Temporary uploads are deleted when
each request completes. Usage metrics exclude filenames, document contents, extracted text, and
table cells. Applications are open while endpoint deployment is completed. Apply without attaching
a document; invitations begin only after the endpoint is verified:

[Apply for free agent beta access](mailto:wesseltl@gmail.com?subject=pdf-mcp%20Free%20Agent%20Beta)

After acceptance, install and configure the separate bridge with the endpoint and key you receive:

```bash
python -m pip install "pdf-agent-mcp[cloud] @ https://github.com/wesseltl/pdf-mcp/releases/download/v0.4.0/pdf_agent_mcp-0.4.0-py3-none-any.whl"
```

```json
{
  "mcpServers": {
    "pdf-cloud": {
      "command": "pdf-agent-cloud-mcp",
      "env": {
        "PDF_MCP_CLOUD_URL": "https://endpoint-provided-with-beta-access.example",
        "PDF_MCP_CLOUD_API_KEY": "key-provided-once"
      }
    }
  }
}
```

Use only redacted or non-sensitive files. See the [free beta terms](BETA_TERMS.md),
[privacy notice](PRIVACY.md), and machine-readable
[`beta/free-hosted-beta.json`](beta/free-hosted-beta.json).

## What it turns a document into

A PDF or Word table like this:

```
Item     Qty   Price
Widget    3    12.50
Gadget    1    40.00
Bolt     10     0.25
```

can be checked against `invoice-lines-v1` and returned as canonical records with an explicit decision:

```json
{
  "decision": "accepted",
  "profile": {"id": "invoice-lines-v1", "version": "1.0.0"},
  "records": [
    {
      "values": {"item": "Widget", "quantity": "3", "unit_price": "12.50"},
      "evidence": {
        "item": {"page": 1, "table_index": 0, "row": 1, "column": 0, "bbox": [242.9, 136.0, 287.7, 154.0]}
      }
    }
  ]
}
```

## The tools it gives an agent

| Tool | What it does |
|---|---|
| `list_extraction_profiles()` | Built-in profile IDs, versions, fields, and hashes |
| `extract_with_profile(path, profile)` | Canonical records, cell evidence, validation issues, and a fail-closed decision |
| `export_with_profile(input_path, profile, output_path)` | Profile-checked `.xlsx`, `.csv`, or `.json`; XLSX includes Review, Data, and Evidence sheets |
| `page_count(path)` | How many pages the PDF has |
| `extract_text(path, page)` | Text per page (one page, or the whole doc) |
| `extract_tables(path, page, merge_multipage)` | Raw rows, source coordinates, and basic parser warnings |
| `table_to_csv(path, page, index)` | One table as clean CSV text |
| `extract_docx_text(path)` | Paragraph text from a `.docx` file |
| `extract_docx_tables(path)` | Word tables as rows of cells, with the same assessment fields and merged-cell warnings |
| `docx_table_to_csv(path, index)` | One Word table as clean CSV text |
| `export_document_tables(input_path, output_path, merge_multipage)` | Export PDF/DOCX tables to `.xlsx`, `.csv`, or `.json` |

## MCP setup for Claude Desktop

The fastest way to use this is with an MCP client like Claude Desktop. Three steps:

**1. Install it**

```bash
python -m pip install "pdf-agent-mcp[mcp] @ https://github.com/wesseltl/pdf-mcp/releases/download/v0.4.0/pdf_agent_mcp-0.4.0-py3-none-any.whl"
```

**2. Add it to your client's config**

Claude Desktop's config lives here:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Add the server:

```json
{
  "mcpServers": {
    "pdf": { "command": "pdf-agent-mcp" }
  }
}
```

**3. Restart Claude Desktop.** You'll see a tools icon appear, meaning the server is connected.

That's it. Now ask about any `.pdf` or `.docx` on your machine:

```
You:  Check /Users/me/invoices/2024-001.pdf with invoice-lines-v1.

Agent (calls extract_with_profile):
  decision: accepted
  records: 3
  issues: 0
```

The agent must route `needs_review` and `rejected` results to a person instead of treating them as
trusted business data.

> **Restricting file access:** to stop the agent reading anything outside one folder, set
> `PDF_MCP_ALLOWED_DIR`. See [SECURITY.md](SECURITY.md).

## Use it with other MCP clients

The same server works in any MCP client, only the config differs. Use `pdf-agent-mcp` as the command.

**Cursor** — `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (per project). Same shape as Claude
Desktop, and it hot-reloads (no restart):

```json
{ "mcpServers": { "pdf": { "command": "pdf-agent-mcp" } } }
```

**VS Code / GitHub Copilot** — `.vscode/mcp.json`. Note the different key (`servers`, not `mcpServers`)
and the required `type`. Tools only run in Copilot **Agent mode**:

```json
{ "servers": { "pdf": { "type": "stdio", "command": "pdf-agent-mcp" } } }
```

**Windsurf** — `~/.codeium/windsurf/mcp_config.json` (create it if missing). Same shape as Claude
Desktop:

```json
{ "mcpServers": { "pdf": { "command": "pdf-agent-mcp" } } }
```

**Cline** — add it from the extension's MCP settings panel in VS Code (command: `pdf-agent-mcp`).

## Profile-checked extraction

The package includes `lab-coa-v1` and `invoice-lines-v1` as reference profiles:

```bash
extract-document-with-profile examples/invoice.pdf invoice-lines-v1 result.xlsx
```

Exit status is 0 for `accepted`, 2 for `needs_review`, and 3 for `rejected`. XLSX output contains
`Review`, `Data`, and `Evidence` sheets. Formula-like document values are escaped in spreadsheet
exports rather than executed.

Profiles are ordinary, versioned JSON contracts. See the
[profile format](https://github.com/wesseltl/pdf-mcp/blob/main/PROFILE_FORMAT.md) and
[machine-readable schema](https://github.com/wesseltl/pdf-mcp/blob/main/profile.schema.json).
Results follow the versioned
[extraction result schema](https://github.com/wesseltl/pdf-mcp/blob/main/extraction-result.schema.json).

## Measure a profile

Measure exact field and record accuracy against local, customer-approved expected rows:

```bash
evaluate-document-profile evaluations/sample-invoice.json
```

The report contains document hashes and aggregate metrics, not document or expected cell values. The
included sample is synthetic; build a representative private set before claiming accuracy for a real
document family. See the
[evaluation guide](https://github.com/wesseltl/pdf-mcp/blob/main/EVALUATION.md).

For a larger demonstration, the repository includes an
[18-document fictional workflow simulation](https://github.com/wesseltl/pdf-mcp/tree/main/evaluations/simulated-customer).
It exercises accepted, review, and rejected outcomes across PDF and DOCX variants. It is regression
coverage authored by the product developer, not customer validation or evidence of demand.

## Raw export

For a direct document-to-file workflow, use the CLI:

```bash
export-document-tables report.pdf report.xlsx
export-document-tables coa.docx coa.xlsx
export-document-tables coa.docx coa.json
```

Raw Excel exports include a `Review` sheet with table locations and parser warnings. Use profile-based
export when a workflow needs canonical fields and an acceptance decision.

## Understanding the output

`extract_tables` returns raw rows and lightweight parser diagnostics:

```json
{
  "page": 1,
  "rows": [ ... ],
  "n_rows": 4,
  "looks_clean": true,
  "column_count": 3,
  "empty_ratio": 0.0,
  "warnings": []
}
```

- **`looks_clean`** — `true` only means these basic diagnostics found no red flag. It is not an
  accuracy score or acceptance decision.
- **`column_count`** — the number of columns, if every row agrees on it (`null` if rows disagree).
- **`empty_ratio`** — fraction of blank cells. A high value often means a bad extraction.
- **`has_merged_cells`** — Word-only flag for tables with merged cells. Word exposes those cells as
  repeated values, so the table is flagged for review.
- **`warnings`** — plain-language flags, e.g. *"ragged: rows have [2, 3, 4] columns (grid may be
  misdetected)"* or *"66% of cells are empty"*. PDF tables are genuinely hard (nested/merged cells,
  multi-page), so instead of pretending, the tool tells you when a result is suspect.

## Also usable from plain Python

```python
from pdf_mcp import docx_extractor, exporter, extractor, verified

result = verified.extract_with_profile("invoice.pdf", "invoice-lines-v1")
if result["decision"] == "accepted":
    rows = [record["values"] for record in result["records"]]

verified.export_with_profile("coa.pdf", "lab-coa-v1", "coa.xlsx")

extractor.extract_tables("invoice.pdf")      # {'tables': [{'rows': [...], 'looks_clean': True, ...}]}
extractor.table_to_csv("invoice.pdf")        # clean CSV of the first table
extractor.extract_text("report.pdf", page=1)

docx_extractor.extract_docx_tables("coa.docx")
docx_extractor.docx_table_to_csv("coa.docx")

exporter.export_document_tables("coa.docx", "coa.xlsx")
```

## Tests

```bash
python -m pip install -e ".[test]"
python -m unittest discover -s tests     # builds synthetic PDFs, runs anywhere
evaluate-document-profile evaluations/sample-invoice.json
evaluate-document-profile evaluations/simulated-customer/development.json
evaluate-document-profile evaluations/simulated-customer/holdout.json
```

## License

MIT

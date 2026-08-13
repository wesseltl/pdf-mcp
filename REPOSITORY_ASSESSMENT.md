# Repository Assessment

## Audit scope

This assessment covers the repository at commit `fb9ae62` on branch
`agent/smart-lab-index-foundation`. The worktree was clean before the audit. The review covered tracked
source, commands, dependencies, document-processing flows, browser and MCP interfaces, release
automation, tests, integrations, fixture contents, and embedded metadata in tracked PDF, DOCX, and
XLSX files.

No application code was changed as part of this audit.

## Executive summary

The repository is a small Python document-table extraction product, not yet a knowledge-indexing
platform. It has useful deterministic PDF and DOCX extraction, cell-level evidence, profile-driven
validation, export safety, local evaluation, MCP adapters, and a secure loopback browser shell. These
are credible inputs to future LabOverlay parser, extraction, export, evaluation, and UI-adapter
modules.

The current package has no durable database, entity model, assertions, source registry, index runs,
filesystem discovery, module registry, lifecycle, event dispatcher, search index, AI provider, or
permission model. Format selection and orchestration use direct imports and suffix conditionals. The
largest concentration is `pdf_mcp/verified.py`, which combines parser selection, mapping, validation,
transient issues, review decisions, provenance assembly, version fingerprints, and export.

The safest strategy is preservation through adapters: define stable LabOverlay contracts, wrap
the tested extractors behind parser modules, and keep the existing public commands working while the
new core is introduced incrementally.

## Repository shape

| Area | Current responsibility | Evidence |
| --- | --- | --- |
| `pdf_mcp/extractor.py` | PDF path checking, page selection, text extraction, table extraction, cell bounding boxes, table assessment, and multipage stitching | [`pdf_mcp/extractor.py:13`](pdf_mcp/extractor.py#L13), [`pdf_mcp/extractor.py:56`](pdf_mcp/extractor.py#L56), [`pdf_mcp/extractor.py:96`](pdf_mcp/extractor.py#L96), [`pdf_mcp/extractor.py:127`](pdf_mcp/extractor.py#L127) |
| `pdf_mcp/docx_extractor.py` | DOCX paragraph and table extraction, merged-cell detection, and table-to-CSV conversion | [`pdf_mcp/docx_extractor.py:14`](pdf_mcp/docx_extractor.py#L14), [`pdf_mcp/docx_extractor.py:17`](pdf_mcp/docx_extractor.py#L17), [`pdf_mcp/docx_extractor.py:33`](pdf_mcp/docx_extractor.py#L33) |
| `pdf_mcp/exporter.py` | PDF/DOCX dispatch plus XLSX, CSV, and JSON rendering | [`pdf_mcp/exporter.py:17`](pdf_mcp/exporter.py#L17), [`pdf_mcp/exporter.py:33`](pdf_mcp/exporter.py#L33), [`pdf_mcp/exporter.py:107`](pdf_mcp/exporter.py#L107) |
| `pdf_mcp/profiles.py` | Strict versioned JSON extraction-profile validation, loading, and hashing | [`pdf_mcp/profiles.py:15`](pdf_mcp/profiles.py#L15), [`pdf_mcp/profiles.py:61`](pdf_mcp/profiles.py#L61), [`pdf_mcp/profiles.py:211`](pdf_mcp/profiles.py#L211) |
| `pdf_mcp/verified.py` | Profile-driven extraction and most workflow policy | [`pdf_mcp/verified.py:236`](pdf_mcp/verified.py#L236), [`pdf_mcp/verified.py:390`](pdf_mcp/verified.py#L390), [`pdf_mcp/verified.py:541`](pdf_mcp/verified.py#L541), [`pdf_mcp/verified.py:587`](pdf_mcp/verified.py#L587) |
| `pdf_mcp/evaluator.py` | Local ground-truth evaluation and content-free metric reports | [`pdf_mcp/evaluator.py:99`](pdf_mcp/evaluator.py#L99), [`pdf_mcp/evaluator.py:216`](pdf_mcp/evaluator.py#L216) |
| `pdf_mcp/server.py` | Local FastMCP tool adapter | [`pdf_mcp/server.py:11`](pdf_mcp/server.py#L11), [`pdf_mcp/server.py:24`](pdf_mcp/server.py#L24) |
| `pdf_mcp/cloud_client.py`, `cloud_server.py` | Explicit opt-in client and MCP bridge to an external hosted extraction API | [`pdf_mcp/cloud_client.py:27`](pdf_mcp/cloud_client.py#L27), [`pdf_mcp/cloud_client.py:87`](pdf_mcp/cloud_client.py#L87), [`pdf_mcp/cloud_server.py:14`](pdf_mcp/cloud_server.py#L14) |
| `pdf_mcp/web_app.py`, `web_ui/` | Local loopback HTTP backend and static no-code conversion UI | [`pdf_mcp/web_app.py:51`](pdf_mcp/web_app.py#L51), [`pdf_mcp/web_app.py:162`](pdf_mcp/web_app.py#L162), [`pdf_mcp/web_ui/index.html:30`](pdf_mcp/web_ui/index.html#L30) |
| `scripts/` | Desktop packaging, launch validation, synthetic evidence generation, and Stripe administration | [`scripts/build_desktop_app.py:132`](scripts/build_desktop_app.py#L132), [`scripts/validate_launch.py:10`](scripts/validate_launch.py#L10), [`scripts/create_stripe_payment_links.py:117`](scripts/create_stripe_payment_links.py#L117) |
| `docs/` | Static public marketing, terms, privacy, and download site | [`.github/workflows/pages.yml:32`](.github/workflows/pages.yml#L32) |

There is one deployable Python package. The apparent source-file separation is useful, but it is not a
module system: there are no manifests, capability interfaces, dependency declarations, enable/disable
states, health states, or lifecycle hooks.

## Commands and entry points

The package publishes six console commands in [`pyproject.toml:31`](pyproject.toml#L31):

| Command | Implementation | Behavior |
| --- | --- | --- |
| `pdf-mcp-app` | `pdf_mcp.web_app:main` | Starts a local browser converter on loopback and opens the system browser. |
| `pdf-agent-mcp` | `pdf_mcp.server:main` | Starts the local FastMCP server over its default stdio transport. |
| `pdf-agent-cloud-mcp` | `pdf_mcp.cloud_server:main` | Starts an MCP bridge that uploads selected files to a configured hosted API. |
| `export-document-tables` | `pdf_mcp.cli:main` | Converts PDF/DOCX tables to XLSX, CSV, or JSON. |
| `extract-document-with-profile` | `pdf_mcp.profile_cli:extract_main` | Runs profile extraction, writes output, and returns decision-specific exit codes. |
| `evaluate-document-profile` | `pdf_mcp.profile_cli:evaluate_main` | Evaluates a profile against a local manifest and optional report path. |

The command layer is thin for raw export, but the MCP server manually declares every concrete tool.
For example, the local MCP adapter directly imports five implementation modules and exposes each
function separately in [`pdf_mcp/server.py:11`](pdf_mcp/server.py#L11) through
[`pdf_mcp/server.py:149`](pdf_mcp/server.py#L149). A new parser or capability currently requires
editing this central adapter.

## Document-processing flows

### Raw conversion

The current raw flow is:

```text
CLI, MCP, or local browser
  -> exporter.extract_document_tables()
  -> suffix switch for PDF or DOCX
  -> concrete extractor
  -> raw table dictionaries
  -> exporter.write_document_tables()
  -> XLSX, CSV, or JSON
```

The suffix switch is in [`pdf_mcp/exporter.py:17`](pdf_mcp/exporter.py#L17) and the direct parser calls
are in [`pdf_mcp/exporter.py:44`](pdf_mcp/exporter.py#L44). Unsupported types fail before any parser
selection abstraction exists. The local browser adds input limits, signature checks, temporary files,
previews, and in-memory downloads around this flow in
[`pdf_mcp/web_app.py:221`](pdf_mcp/web_app.py#L221).

### Profile-checked conversion

The profile flow is separate rather than layered on a common parser contract:

```text
CLI or MCP
  -> verified.extract_with_profile()
  -> load and validate profile
  -> inspect and hash one file
  -> suffix switch for PDF or DOCX
  -> concrete extractor
  -> header matching and typed conversion
  -> transient records, evidence, and issue dictionaries
  -> accepted / needs_review / rejected decision
  -> extraction fingerprint
  -> optional XLSX, CSV, or JSON writer
```

The direct parser dispatch is in [`pdf_mcp/verified.py:390`](pdf_mcp/verified.py#L390). Mapping and
record evidence are assembled in [`pdf_mcp/verified.py:236`](pdf_mcp/verified.py#L236). Decision policy
is embedded in [`pdf_mcp/verified.py:480`](pdf_mcp/verified.py#L480), and export begins in
[`pdf_mcp/verified.py:587`](pdf_mcp/verified.py#L587). This path bypasses `exporter.extract_document_tables`
and duplicates format dispatch and output concerns.

### Existing normalized structures

The extraction dictionaries are useful precursors but not a universal `DocumentContent` contract:

- PDF text is returned as page dictionaries in [`pdf_mcp/extractor.py:56`](pdf_mcp/extractor.py#L56).
- DOCX text is returned as paragraphs plus one flattened string in
  [`pdf_mcp/docx_extractor.py:17`](pdf_mcp/docx_extractor.py#L17).
- PDF table cells can carry page and bounding-box coordinates in
  [`pdf_mcp/extractor.py:96`](pdf_mcp/extractor.py#L96).
- DOCX table cells carry table, row, and column indexes but no structural path beyond those indexes in
  [`pdf_mcp/docx_extractor.py:39`](pdf_mcp/docx_extractor.py#L39).
- No source ID, document ID, heading model, sheet model, common text-block model, or permission metadata
  is part of these parser outputs.

XLSX, CSV, and TXT are output formats or profile data, not input parsers. `openpyxl` is used to write
workbooks in [`pdf_mcp/exporter.py:107`](pdf_mcp/exporter.py#L107) and
[`pdf_mcp/verified.py:587`](pdf_mcp/verified.py#L587); there is no XLSX ingestion implementation.

## Backend and frontend

### Local backend

The local app uses Python's `ThreadingHTTPServer`, not a web framework
([`pdf_mcp/web_app.py:16`](pdf_mcp/web_app.py#L16)). It is deliberately limited to one conversion
workflow. State consists of a random session token and bounded in-memory download objects
([`pdf_mcp/web_app.py:51`](pdf_mcp/web_app.py#L51)). There is no user account, database, task queue,
index, or restart persistence.

Positive local security properties include:

- loopback-only binding and nearby-port selection ([`pdf_mcp/web_app.py:345`](pdf_mcp/web_app.py#L345));
- host, origin, and constant-time session-token checks ([`pdf_mcp/web_app.py:306`](pdf_mcp/web_app.py#L306));
- restrictive response headers and no CORS ([`pdf_mcp/web_app.py:336`](pdf_mcp/web_app.py#L336));
- upload, page, output, retained-byte, download-count, and TTL limits
  ([`pdf_mcp/web_app.py:24`](pdf_mcp/web_app.py#L24)); and
- temporary input/output deletion after conversion ([`pdf_mcp/web_app.py:234`](pdf_mcp/web_app.py#L234)).

The handler catches a conversion failure for one request, but there is no batch/index-run failure
isolation, process timeout, parser worker boundary, or concurrency limiter. Those become important when
moving from user-selected files to automatic recursive discovery.

### Local frontend

The application frontend is packaged vanilla HTML, CSS, and JavaScript. It has no package manager or
runtime CDN dependency. It supports file selection, output format, one parser option, result warnings,
preview, download, and shutdown ([`pdf_mcp/web_ui/index.html:30`](pdf_mcp/web_ui/index.html#L30),
[`pdf_mcp/web_ui/app.js:119`](pdf_mcp/web_ui/app.js#L119)).

Navigation and views are static and converter-specific. There is no route registry, capability model,
module-contributed navigation, entity view, source view, issue queue, or settings surface. The local UI
contains user-initiated external GitHub links ([`pdf_mcp/web_ui/index.html:17`](pdf_mcp/web_ui/index.html#L17),
[`pdf_mcp/web_ui/index.html:141`](pdf_mcp/web_ui/index.html#L141)); these would need to be hidden or
blocked under a strict no-egress policy.

### Public website

The public site is static content deployed from `docs/` to GitHub Pages on every push to `main`
([`.github/workflows/pages.yml:3`](.github/workflows/pages.yml#L3),
[`.github/workflows/pages.yml:32`](.github/workflows/pages.yml#L32)). Its offer script fetches public
JSON from `raw.githubusercontent.com` at runtime ([`docs/offers.js:1`](docs/offers.js#L1),
[`docs/offers.js:61`](docs/offers.js#L61)). This site is distribution/marketing infrastructure, not the
local product UI, and it is not offline-capable.

## Storage and domain model

No ORM, migration, SQL schema, database file, database dependency, or durable repository abstraction is
present. Current persistence is limited to explicit export files, JSON configuration/evaluation files,
and release/offer metadata. Browser downloads are process memory only.

The repository has no canonical entities, aliases, relationships, assertions, source records,
documents, issues, index runs, audit events, review decisions, or resolved-value model. The `records`,
`evidence`, and `issues` returned by profile extraction are operation-scoped dictionaries described by
[`extraction-result.schema.json:44`](extraction-result.schema.json#L44) and
[`extraction-result.schema.json:89`](extraction-result.schema.json#L89). They should not be mistaken for
the future durable LabOverlay domain model.

## Dependencies

Runtime support is Python 3.10 or newer. The three unconditional dependencies are
`pdfplumber>=0.11`, `python-docx>=1.1`, and `openpyxl>=3.1`
([`pyproject.toml:12`](pyproject.toml#L12)). Consequently, PDF parsing, DOCX parsing, and XLSX export are
installed as one inseparable base package today.

Optional dependency groups are:

- `mcp`: FastMCP;
- `cloud`: FastMCP and HTTPX;
- `test`: ReportLab and HTTPX;
- `commerce`: Stripe; and
- `desktop-build`: PyInstaller.

These are declared in [`pyproject.toml:16`](pyproject.toml#L16). There is no lockfile and no upper bound
on any declared dependency. Runtime package versions are captured only in the profile-extraction audit
for the selected PDF or DOCX engine ([`pdf_mcp/verified.py:395`](pdf_mcp/verified.py#L395)).

## Configuration and integrations

Configuration is distributed across environment variables and constants rather than one schema:

- `PDF_MCP_ALLOWED_DIR` is read into a module global at PDF extractor import time
  ([`pdf_mcp/extractor.py:13`](pdf_mcp/extractor.py#L13));
- hosted URL, API key, and upload limit are read by `CloudConfig.from_env()`
  ([`pdf_mcp/cloud_client.py:27`](pdf_mcp/cloud_client.py#L27)); and
- `STRIPE_SECRET_KEY` is read only by the administrative payment-link script
  ([`scripts/create_stripe_payment_links.py:117`](scripts/create_stripe_payment_links.py#L117)).

External integrations are limited to:

- FastMCP for local and cloud-bridge tool exposure;
- an HTTPX client for an operator-supplied hosted extraction endpoint;
- Stripe in an administrative script, not document processing;
- GitHub Pages, GitHub Releases, PyPI, and MCP Registry release automation.

The repository contains the hosted API client contract, but not the hosted HTTP backend. The public
beta metadata explicitly says the endpoint is pending in
[`beta/free-hosted-beta.json:38`](beta/free-hosted-beta.json#L38), and launch validation enforces that
state in [`scripts/validate_launch.py:146`](scripts/validate_launch.py#L146).

## AI providers

There is no OpenAI, Anthropic, Ollama, llama.cpp, embedding, vector database, or model-runtime
integration in application code. Current extraction is intentionally parser-driven; the product
description states that cell values come from document parsers rather than model output
([`README.md:14`](README.md#L14)). This is a good foundation for deterministic indexing. Future AI
must be added as optional capabilities rather than inserted into these parser functions.

## Deployment and packaging

The product is distributed as:

1. a Python package and console commands;
2. PyInstaller desktop archives for Linux, Windows, and macOS; and
3. a static GitHub Pages site.

The publish workflow runs tests and launch checks, builds Python distributions, and builds/smoke-tests
desktop applications on all three operating systems
([`.github/workflows/publish.yml:13`](.github/workflows/publish.yml#L13),
[`.github/workflows/publish.yml:51`](.github/workflows/publish.yml#L51)). PyPI and MCP Registry writes
are tag- and configuration-gated ([`.github/workflows/publish.yml:111`](.github/workflows/publish.yml#L111)).
There is no container image, service deployment manifest, installer with service management, or local
database migration path.

The desktop build bundles the same web application as a windowed PyInstaller executable and performs
an HTTP startup smoke test ([`scripts/build_desktop_app.py:49`](scripts/build_desktop_app.py#L49),
[`scripts/build_desktop_app.py:132`](scripts/build_desktop_app.py#L132)). The resulting community beta
is unsigned, as stated in [`scripts/build_desktop_app.py:109`](scripts/build_desktop_app.py#L109).

## Tests and verification

There are 103 `unittest` test methods across 12 test files. Coverage is strongest around parser edge
cases, profile decisions, evidence, spreadsheet safety, web-session protections, cloud-client request
shape, offer/launch policy, and synthetic evaluation claims. Representative suites are:

- [`tests/test_extractor.py:83`](tests/test_extractor.py#L83);
- [`tests/test_docx_extractor.py:51`](tests/test_docx_extractor.py#L51);
- [`tests/test_verified.py:71`](tests/test_verified.py#L71);
- [`tests/test_web_app.py:79`](tests/test_web_app.py#L79); and
- [`tests/test_simulated_evidence.py:31`](tests/test_simulated_evidence.py#L31).

Audit verification with the repository `.venv` produced:

```text
.venv/bin/python -m unittest discover -s tests -v
Ran 103 tests in 8.063s
OK

sample evaluation: passed, 1 case, all configured metrics 1.0
development evaluation: passed, 12 cases, all configured metrics 1.0
holdout evaluation: passed, 6 cases, all configured metrics 1.0

.venv/bin/python scripts/validate_launch.py
Validated 2 paid offers, 1 hosted beta offer, and 19 public launch files.
```

The evaluation pack is explicitly authored synthetic regression coverage, not real customer evidence
([`evaluations/simulated-customer/README.md:1`](evaluations/simulated-customer/README.md#L1),
[`evaluations/simulated-customer/README.md:53`](evaluations/simulated-customer/README.md#L53)).

CI runs unit tests and the three evaluation gates on Ubuntu for Python 3.10, 3.11, and 3.12
([`.github/workflows/ci.yml:13`](.github/workflows/ci.yml#L13)). It does not run coverage, type checking,
Ruff, module-boundary tests, migration tests, or automatic hostile-document resource tests. A local
`.venv/bin/ruff check .` audit reported 30 findings; lint is not currently a CI gate.

## Safely reusable functionality

| Functionality | LabOverlay destination | Reuse assessment |
| --- | --- | --- |
| PDF text/table extraction and cell bounding boxes | `parser.pdf` | Reuse algorithms and tests behind a normalized parser adapter. Remove file-policy ownership and private shared helpers from the PDF implementation. |
| DOCX paragraph/table extraction and merged-cell signal | `parser.docx` | Reuse behind the same normalized parser contract. Extend structural provenance before persistence. |
| Header normalization, strict profile validation, and profile hashing | structured extractor configuration or a document-intelligence module | Strong reusable deterministic logic. It is not a Core entity schema. |
| Header matching, typed conversion, raw/normalized value preservation | `extractor.structured` | Extract from `verified.py`; emit candidates/assertions through Core services instead of final workflow records. |
| PDF cell evidence and extraction fingerprints | Core provenance/index-run support plus parser adapters | Reuse concepts and hashing mechanics. Replace package-specific field names and hardcoded schema URLs. |
| Table diagnostics and merged-cell warnings | parser diagnostics or issue-rule modules | Reuse behavior, but move `_assess` out of the PDF module and represent findings through a stable issue contract. |
| Spreadsheet formula defense | optional export module | Reuse directly with focused tests. |
| Ground-truth evaluator | development/evaluation tooling | Keep outside the small runtime Core. Generalize it later to module/version-aware index evaluations. |
| Loopback binding, session token, CSP, bounded in-memory downloads | local UI host | Reuse security patterns. Replace converter-specific routing and static navigation. |
| FastMCP wrappers | optional MCP interface module | Rebuild tool registration from capabilities; do not make FastMCP a Core dependency. |
| Streaming SHA-256 in `verified._document` | filesystem connector/source service | Reuse the technique, not the format-specific private function. |

## Capabilities that do not exist yet

The following LabOverlay foundations require new design rather than refactoring labels onto current
code:

- stable Core domain models and repositories;
- SQLite or another local durable store plus migrations;
- source records and recursive incremental filesystem discovery;
- changed/deleted/inaccessible source handling;
- a normalized parser contract for PDF, DOCX, XLSX, CSV, and TXT;
- module manifests, registry, dependency checks, configuration, enablement, lifecycle, and health;
- assertions, aliases, controlled predicates, resolution evidence, and non-destructive current values;
- durable issues, review decisions, audit events, and index runs;
- in-process events/hooks and per-module failure isolation;
- entity and lexical search;
- capability-driven entity/source/issue/module UI;
- explicit no-egress policy enforcement; and
- source permission metadata preservation.

## Highest-risk findings

1. **No domain or storage foundation exists.** Current operation-scoped extraction dictionaries cannot
   safely become the durable entity/assertion model by accretion.
2. **Parser selection is concrete and duplicated.** Both `exporter.py` and `verified.py` directly switch
   on PDF/DOCX and import implementations, so new parsers require central edits.
3. **`verified.py` is a workflow monolith.** Its 708 lines combine at least seven future module/Core
   responsibilities.
4. **Automatic indexing would amplify parser risk.** Local parsing has file-size/page limits in the web
   adapter but no parser subprocess, timeout, per-run isolation, or batch continuation contract.
5. **No-egress is descriptive, not enforceable.** Local and cloud behavior are separate today, but no
   `SMART_LAB_INDEX_NO_EGRESS` policy can reject network-capable modules or external UI navigation.
6. **Provenance is useful but incomplete for an index.** Cell coordinates exist, while source identity,
   structural references across all formats, extraction method/version, assertion status, and durable
   lineage do not.
7. **Quality gates do not enforce architecture or static analysis.** Behavioral tests pass, but there
   are no dependency-boundary, module-disablement, failure-isolation, migration, type-check, coverage,
   or lint gates.

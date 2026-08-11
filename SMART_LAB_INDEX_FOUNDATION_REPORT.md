# Smart Lab Index Foundation Report

Date: 2026-08-11

Branch: `agent/smart-lab-index-foundation`

Foundation/Core API version: `0.1.0`

Post-foundation updates add the local capability-aware operator GUI in Smart Lab Index `0.2.0` and
native folder selection, source switching, isolated picker workspaces, and standalone desktop
packaging in `0.3.0`. Version `0.4.0` adds a zero-dependency browser folder navigator, exact-origin
enforcement, checksummed archives, certificate-driven platform signing/notarization hooks, and a
public request-only beta page built around actual product output. Version `0.5.0` adds bounded source
preflight, progress and cancellation, parser resource budgets, broader deterministic extraction,
server-side local search, extraction-coverage reporting, calibration issues, and auditable issue
review. The foundation findings remain the record for the `0.1.0` iteration; the validation and
limitations sections include the current post-update state.

## Existing Architecture

The repository started as `pdf-agent-mcp` 0.4.0. It provided deterministic PDF and DOCX table/text
extraction, profile validation, exports, a local MCP server, a loopback browser converter, an
explicit hosted bridge, and synthetic evaluation fixtures. The tree was clean at baseline commit
`fb9ae62`, and 103 tests passed.

The existing product had no durable entity/assertion index, source inventory, index-run history,
module registry, module lifecycle, or normalized connector/parser contracts. Dispatch occurred by
calling concrete document implementations. `pdf_mcp.verified` combined loading, extraction,
validation, evidence, review decisions, and result assembly in one document-workflow pipeline.

The document product was retained as a compatibility layer. Stripe administration, the public site,
CI/release automation, and the optional hosted bridge remain outside the Smart Lab Index runtime.

Detailed audit artifacts:

- [REPOSITORY_ASSESSMENT.md](REPOSITORY_ASSESSMENT.md)
- [ORGANIZATION_COUPLING_AUDIT.md](ORGANIZATION_COUPLING_AUDIT.md)
- [MODULARITY_ASSESSMENT.md](MODULARITY_ASSESSMENT.md)

## Modularity Assessment

The reusable parsing behavior was sound, local, deterministic, and source-read-only, but its
boundaries were document-tool boundaries rather than product module boundaries. Important coupling
included direct extension dispatch, parsers opening paths themselves, imports of private parser
helpers, process-wide path configuration, and application services calling concrete implementations.

The new product therefore uses a modular monolith. Core never imports built-in implementation
modules. Modules import public Core contracts and value objects, not one another. The explicit
composition root is the only layer that imports both Core and concrete modules. Modules do not
receive a raw SQLite connection or a write-capable Core repository.

The registry is deliberately for installed capability providers, not configured source instances.
One `connector.filesystem` provider can serve multiple independently bound `SourceDefinition`
instances. This avoids both a connector registration per folder and false cross-source deletion.

## New Modular Architecture

### Core

`smart_lab_index.core` owns universal entities, source/document identity, assertions, provenance,
issues, reviews, audits, index runs, runtime policy, module contracts/registry, synchronous event
hooks, normalization helpers, and durable SQLite storage.

Core entity categories are `ORGANIZATION`, `ORGANIZATIONAL_UNIT`, `LOCATION`, `ASSET`, `PERSON`,
`DOCUMENT`, `PROCESS`, and `SOURCE_SYSTEM`. Laboratory terms such as `FREEZER` and `ROOM` are
subtypes supplied by `domain.general_lab`; they are not Core tables.

### Module Registry

Every module has a validated manifest with ID, release version, type, Core compatibility,
capabilities, dependencies, configuration schema, lifecycle, health, and security/resource
declarations. The registry records installed/enabled/blocked state, validates dependencies, starts in
dependency order, stops in reverse start order, isolates optional startup failures, redacts
configuration snapshots, and enforces no-egress before module initialization.

Built-ins are registered explicitly. There is no dynamic code discovery, marketplace, generic
service container, or process-per-module deployment.

### Module Contracts

Connectors return `DiscoveryBatch` and `SourceRecord` values and expose read-only content streams.
Parsers accept a path-safe `DocumentSource` plus a byte stream and return normalized
`DocumentContent`. Extractors return candidates and assertion drafts. Resolvers and issue rules use
narrow read-only repository protocols. Issue rules return drafts; Core deduplicates and persists them.

The in-process event bus runs post-commit hooks. A failing hook is recorded and does not prevent later
handlers. It is not a distributed broker.

### Indexing

The application service composes connector, parser, extractor, resolver, and issue capabilities. It
uses source generations so changed, deleted, and restored records remain historically traceable.
Assertion uniqueness is generation-scoped, preventing A-to-B-to-A restoration bugs.

A processing ledger keys completed work by document generation, module version/configuration, and
resolver/domain context. Parser or intelligence-component changes therefore trigger controlled
reprocessing. Extractor output and supersession are transactional. A failed changed generation keeps
the last successful assertions active, and a resolver failure cannot leave partial entities or
assertions committed.

### Connectors

`connector.filesystem` performs recursive read-only discovery, SHA-256 change detection, conservative
deletion inference, per-path failure isolation, permission metadata capture, and bounded immutable
content snapshots. It rejects non-regular files, symlinks, root escapes, source-ID rebinding, and a
Core database inside the source root. A metadata-only preflight applies configurable file-count,
aggregate-byte, per-file, and exclusion limits before hashing. Runs report phase/count/byte progress
and may be cancelled between files without inferring deletions from an incomplete scan.

### Parsers

PDF, DOCX, XLSX, CSV, and TXT modules return text blocks, tables, metadata, warnings, and structural
provenance. Parser selection is capability-based and priority-aware; ambiguous equal-priority matches
fail explicitly. Byte, page, text, block, row, cell, Office-entry, and expanded-archive budgets reject
oversized inputs. One parser or document failure does not abort other records.

### Extractors, Resolvers, And Issues

The deterministic extractors detect headers within the first ten table rows and support common asset,
location, person, organization, responsibility, serial/model/status, calibration, and maintenance
columns plus narrow rule-based text relationships. Per-document coverage and unmapped-table warnings
are retained. Resolution runs exact identifier, alias, then normalized-name providers. A candidate
with a distinct explicit identifier cannot be merged by a later name resolver.

`issue.conflicting_location` compares active assertions, preserves both observations, and emits an
evidence-backed issue. `issue.calibration_due` identifies invalid and overdue calibration dates.
`issue.missing_responsibility` is installed but disabled until an operator confirms the indexed scope
is authoritative enough for absence to be meaningful. Conflict review confirms selected evidence,
rejects alternatives without deleting them, and records a review decision plus audit event. Materially
new evidence reopens the issue.

### AI And Search Modules

Inference, embedding, and pluggable search remain reserved module categories; no AI or embedding
provider is installed. The initial Core query service provides bounded local lexical and entity
search across the complete SQLite index. Core has no Ollama, cloud model, embedding vendor, vector
database, or semantic-search dependency. Basic indexing and search work with those categories absent.

### UI Capability Model

Module snapshots expose capabilities, lifecycle, health, settings, and security metadata to the
capability-aware local interface. The `smart-lab-index-app` workspace derives navigation and module
status from those snapshots and indexed entity categories; it does not require each module to edit a
central navigation component. Modules cannot yet inject arbitrary frontend code, which keeps the
first-party modular monolith small and avoids a premature browser plugin framework. The JSON CLI
remains available for automation and diagnostics.

## Modules Implemented

Fifteen modules are installed. Fourteen are enabled and healthy in the synthetic composition;
`issue.missing_responsibility` is deliberately disabled by default.

| ID | Purpose | Version | Dependencies | Default status |
|---|---|---:|---|---|
| `connector.filesystem` | Bounded read-only incremental source discovery | `0.2.0` | None | Enabled / healthy |
| `parser.pdf` | Born-digital PDF text/table normalization | `0.2.0` | None | Enabled / healthy |
| `parser.docx` | Word paragraph/table normalization | `0.2.0` | None | Enabled / healthy |
| `parser.xlsx` | Workbook sheet/cell normalization | `0.2.0` | None | Enabled / healthy |
| `parser.csv` | Delimited row/cell normalization | `0.2.0` | None | Enabled / healthy |
| `parser.txt` | Plain-text block normalization | `0.2.0` | None | Enabled / healthy |
| `domain.general_lab` | Broad synthetic lab terminology and rules | `0.2.0` | None | Enabled / healthy |
| `extractor.structured` | Header-aware table entities and relationships | `0.2.0` | `domain.extraction_rules >= 1.0.0` | Enabled / healthy |
| `extractor.rules` | Configured text relationship candidates | `0.1.0` | `domain.extraction_rules >= 1.0.0` | Enabled / healthy |
| `resolver.identifier` | Exact identifier resolution | `0.1.0` | None | Enabled / healthy |
| `resolver.alias` | Unique alias resolution | `0.1.0` | None | Enabled / healthy |
| `resolver.normalized_name` | Unique normalized-name resolution | `0.1.0` | None | Enabled / healthy |
| `issue.conflicting_location` | Detect incompatible active locations | `0.1.0` | None | Enabled / healthy |
| `issue.calibration_due` | Detect invalid and overdue calibration dates | `0.1.0` | None | Enabled / healthy |
| `issue.missing_responsibility` | Detect assets without responsibility evidence | `0.1.0` | None | Disabled by default |

## Reused Functionality

The existing `pdf_mcp` package remains operational. Its table assessment logic now delegates to the
shared parser-module helper, removing one duplicated implementation. The Smart Lab PDF and DOCX
modules preserve the proven `pdfplumber` and `python-docx` parsing approach while converting output
to normalized, provenance-rich Core contracts. Existing PDF/DOCX extraction, export, profile,
evaluation, MCP, and browser workflows continue to pass their tests.

No existing document feature was deleted. It is now the compatibility/document-ingestion layer, not
the Smart Lab Index Core.

## Organization Independence

No customer-specific production behavior was found in the Python runtime. Existing `Northstar
Water` evaluation data is explicitly fictional and remains isolated under synthetic evaluation
fixtures. Seller/payment metadata and public-site copy are outside Core and module behavior.

New fixtures use only synthetic values such as `Freezer-001`, `Room A-101`, `Room A-102`, and `Alex
Example`. The Core contains no hospital, university, country, language, customer, LIMS, QMS, CMMS,
ELN, or vendor-specific assumptions. Customer differences are represented by installed modules and
configuration, not forks.

## Security

All 15 built-in manifests declare network access `NONE`, no credentials, no telemetry, no automatic
downloads, no subprocesses, and no source writes. Only the filesystem connector declares source
file reads; parsers receive streams. The registry rejects source-writing modules in every mode and
blocks non-loopback network access, telemetry, and automatic downloads when
`SMART_LAB_INDEX_NO_EGRESS=true`.

The retained hosted bridge checks no-egress before reading cloud configuration, resolving/opening a
document, or constructing an HTTP client. It is never an automatic fallback. A test intercepting
socket connection calls during a full built-in indexing run observed zero attempts.

Filesystem reads use root confinement, regular-file checks, no-follow opens where available,
device/inode verification, a 100 MiB read bound, immutable snapshots, and checksum revalidation.
State is rejected inside a source root. State directories use mode `0700`; SQLite database/WAL/SHM
files use `0600`; database hardlinks are rejected. POSIX owner, group, mode, and effective-process
access are retained as inventory metadata; rich Windows/Active Directory/network-share ACLs are not
captured or enforced.

This is application policy, not a hostile-code sandbox. Structural parser limits now include Office
expanded-archive budgets, but process-level CPU/memory/wall-clock isolation, dependency pinning/offline
bundles, application-level encryption, packaged socket-level tests, and OS firewall/service-account
controls remain release gates for confidential lab data.
See [SECURITY_NO_EGRESS_REVIEW.md](SECURITY_NO_EGRESS_REVIEW.md).

## Database

Core owns one local SQLite database with schema version 2. Modules cannot access its connection.
Tables cover migrations, module state, index runs, source bindings, source generations, document
generations, entities, aliases, assertions, document-processing ledger entries, issues, review
decisions, and audit events.

Assertions retain document/source generation, checksum, parser/extractor version, confidence,
status, and structural provenance. Original observations remain queryable after supersession or
deletion. SQLite is sufficient for this graph-shaped first iteration; no Neo4j, cloud database, or
per-module database was introduced.

Schema version 2 has a tested forward migration from version 1 and adds per-document extraction counts
and warnings. This is not yet a mature production migration history.

## Tests

Validation completed on 2026-08-11:

- Full repository suite: 183 tests passed in 17.808 seconds.
- Focused Smart Lab suite: 77 tests passed in 9.530 seconds.
- Ruff: all new Smart Lab code/tests and touched cloud bridge files passed.
- Existing sample, simulated development, and simulated holdout evaluation gates passed with 1.0
  field precision/recall/F1, exact-record rate, and decision accuracy.
- Wheel and source distribution built successfully; `twine check` passed for both.
- The Smart Lab Index `0.5.0` Linux standalone executable completed its packaged synthetic no-egress
  smoke test with 4 sources, 4 documents, 4 entities, 3 assertions, and 1 open issue. Its generated
  SHA-256 manifest verified. The release workflow builds equivalent artifacts on Windows and macOS.
- The `0.5.0` GUI completed fresh desktop and 390-pixel mobile browser checks with HTTP 200, no
  console/page errors, no mobile horizontal overflow, eight bounded search results for the synthetic
  asset, a visible top-of-dialog review form, and a successfully persisted review decision.

Coverage includes the loopback GUI session/exact-origin/CSP controls, authenticated source switching,
native and browser picker path validation, same-port session rotation, isolated picker workspaces,
release checksum/signing helpers, and full
GUI-triggered incremental indexing with provenance, progress, cancellation, search, and review. It
also covers bounded source preflight/exclusions, module registration, disable,
dependencies, policy blocking before initialization, event failure isolation, private state modes,
multiple source instances, checksummed incremental discovery, symlink/special-file handling, all
parser contracts and resource budgets, parser replacement, realistic title-row extraction,
calibration and responsibility issue configuration, conflict provenance and review reopening,
changed/deleted/restored generations, failed-change rollback, processing invalidation, explicit-ID
separation, bounded projections, read-only facades, and no socket attempts by built-ins.
The synthetic Office generator is also checked for byte-identical output across different folders.

## Demonstration

From the repository root:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/smart-lab-index index examples/smart_lab_index/sample_lab \
  --database .smart-lab-index-demo.db --source-id lab-alpha --no-egress
.venv/bin/smart-lab-index inspect --database .smart-lab-index-demo.db
.venv/bin/smart-lab-index modules examples/smart_lab_index/sample_lab --no-egress
.venv/bin/smart-lab-index-app examples/smart_lab_index/sample_lab \
  --database .smart-lab-index-demo.db --source-id lab-alpha --no-egress
```

The first index run reports 4 new/parsed documents, 4 entities, 3 assertions, 1 issue, and no
failures. `inspect` shows both:

```text
Freezer-001 located_in Room A-101
  equipment.xlsx / Assets / D2

Freezer-001 located_in Room A-102
  SOPs/SOP_freezers.docx / paragraph 2
```

It also shows one `CONFLICTING_LOCATION` issue referencing both assertion IDs. The GUI can search the
entire local index, display extraction coverage, and confirm either location with a required audit
note. Running the same `index` command again reports 4 unchanged documents and parses 0 documents.

For another folder, omit `--source-id` to derive a stable ID from the canonical root:

```bash
smart-lab-index index /path/to/read-only/lab-folder --no-egress
smart-lab-index status
```

## Current Limitations

- This is a modular foundation, not a production release for confidential laboratory data.
- The graphical UI is a local single-user operator workspace. It does not provide multi-user
  authentication, role-based access control, review-decision reversal, or source-permission
  enforcement. Permission metadata is retained but not applied to queries.
- Standalone archives are ZIP applications, not native installers. They remain unsigned until real
  publisher credentials are configured; SHA-256 manifests are generated for verification.
- Only the filesystem connector and one broad general-lab domain pack exist.
- Deterministic extraction recognizes common table headers and a narrow text relation; it is not
  general document understanding and still requires site-specific mapping validation.
- Source-authority projection, configurable terminology, export modules, local inference, embeddings,
  semantic search, OCR, and vendor connectors are absent.
- Parsers enforce structural/resource budgets but run in-process without OS-enforced CPU, memory, or
  wall-clock isolation. Do not index hostile or unapproved document trees.
- SQLite content is owner-restricted but plaintext. Use encrypted storage and a dedicated OS account
  for controlled evaluation.
- The distribution still has the compatibility identity `pdf-agent-mcp` `0.5.0`; select and validate
  a distinct Smart Lab Index release identity before publishing this branch.
- Dynamic third-party installation is intentionally absent. Built-in module boundaries are ready;
  a plugin marketplace is not.

## Next Iteration

Implement **process-isolated parsing**: execute each parser in a bounded local worker with enforced
CPU, memory, wall-clock, temporary-file, and serialized-output limits, preserve bounded parser-failure
issues, and verify the packaged artifact under socket-denied no-egress tests. This is the single
highest-value next step before expanding controlled pilots to untrusted or broadly writable document
trees.

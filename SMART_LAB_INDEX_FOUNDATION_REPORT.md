# Smart Lab Index Foundation Report

Date: 2026-08-11

Branch: `agent/smart-lab-index-foundation`

Foundation/Core API version: `0.1.0`

Post-foundation updates add the local capability-aware operator GUI in Smart Lab Index `0.2.0` and
native folder selection, source switching, isolated picker workspaces, and standalone desktop
packaging in `0.3.0`. The foundation findings remain the record for the `0.1.0` iteration; the
validation and limitations sections include the current post-update state.

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
Core database inside the source root.

### Parsers

PDF, DOCX, XLSX, CSV, and TXT modules return text blocks, tables, metadata, warnings, and structural
provenance. Parser selection is capability-based and priority-aware; ambiguous equal-priority matches
fail explicitly. One parser or document failure does not abort other records.

### Extractors, Resolvers, And Issues

The first deterministic extractors support configured spreadsheet structures and narrow rule-based
text relationships. Resolution runs exact identifier, alias, then normalized-name providers. A
candidate with a distinct explicit identifier cannot be merged by a later name resolver.

`issue.conflicting_location` compares active assertions, preserves both observations, and emits an
evidence-backed issue. Issue creation never overwrites an assertion.

### AI And Search Modules

Inference, embedding, and search are reserved module categories, but no provider is installed. Core
has no Ollama, cloud model, embedding vendor, vector database, or semantic-search dependency. Basic
indexing works with those categories absent.

### UI Capability Model

Module snapshots expose capabilities, lifecycle, health, settings, and security metadata for a
future capability-aware interface. The current operator surface is the local `smart-lab-index` JSON
CLI. No Smart Lab Index browser UI or frontend plugin framework was added in this foundation.

## Modules Implemented

All default modules are enabled and healthy in the synthetic composition.

| ID | Purpose | Version | Dependencies | Default status |
|---|---|---:|---|---|
| `connector.filesystem` | Read-only incremental source discovery | `0.1.0` | None | Enabled / healthy |
| `parser.pdf` | Born-digital PDF text/table normalization | `0.1.0` | None | Enabled / healthy |
| `parser.docx` | Word paragraph/table normalization | `0.1.0` | None | Enabled / healthy |
| `parser.xlsx` | Workbook sheet/cell normalization | `0.1.0` | None | Enabled / healthy |
| `parser.csv` | Delimited row/cell normalization | `0.1.0` | None | Enabled / healthy |
| `parser.txt` | Plain-text block normalization | `0.1.0` | None | Enabled / healthy |
| `domain.general_lab` | Broad synthetic lab terminology and rules | `0.1.0` | None | Enabled / healthy |
| `extractor.structured` | Configured table entity/relationship candidates | `0.1.0` | `domain.extraction_rules >= 1.0.0` | Enabled / healthy |
| `extractor.rules` | Configured text relationship candidates | `0.1.0` | `domain.extraction_rules >= 1.0.0` | Enabled / healthy |
| `resolver.identifier` | Exact identifier resolution | `0.1.0` | None | Enabled / healthy |
| `resolver.alias` | Unique alias resolution | `0.1.0` | None | Enabled / healthy |
| `resolver.normalized_name` | Unique normalized-name resolution | `0.1.0` | None | Enabled / healthy |
| `issue.conflicting_location` | Detect incompatible active locations | `0.1.0` | None | Enabled / healthy |

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

All 13 built-in manifests declare network access `NONE`, no credentials, no telemetry, no automatic
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
files use `0600`; database hardlinks are rejected.

This is application policy, not a hostile-code sandbox. Parser CPU/time/memory/expanded-archive
limits, dependency pinning/offline bundles, application-level encryption, packaged socket-level
tests, and OS firewall/service-account controls remain release gates for confidential lab data.
See [SECURITY_NO_EGRESS_REVIEW.md](SECURITY_NO_EGRESS_REVIEW.md).

## Database

Core owns one local SQLite database with schema version 1. Modules cannot access its connection.
Tables cover migrations, module state, index runs, source bindings, source generations, document
generations, entities, aliases, assertions, document-processing ledger entries, issues, review
decisions, and audit events.

Assertions retain document/source generation, checksum, parser/extractor version, confidence,
status, and structural provenance. Original observations remain queryable after supersession or
deletion. SQLite is sufficient for this graph-shaped first iteration; no Neo4j, cloud database, or
per-module database was introduced.

No migration from an older product database was required because the baseline had no durable
knowledge store. Schema version 1 is not yet a production migration history.

## Tests

Validation completed on 2026-08-11:

- Full repository suite: 159 tests passed in 15.278 seconds.
- Focused Smart Lab suite: 54 tests passed in 6.991 seconds.
- Ruff: all new Smart Lab code/tests and touched cloud bridge files passed.
- Existing sample, simulated development, and simulated holdout evaluation gates passed with 1.0
  field precision/recall/F1, exact-record rate, and decision accuracy.
- Wheel and source distribution built successfully; `twine check` passed for both.
- A wheel installed into a separate environment and its `smart-lab-index` entry point completed the
  no-egress synthetic run from outside the source checkout.
- The compatibility distribution wheel containing the Smart Lab Index `0.2.0` GUI installed into a
  separate environment, served all bundled assets, and completed the synthetic no-egress index
  through `smart-lab-index-app` from outside the checkout.
- The Smart Lab Index `0.3.0` Linux standalone executable completed the packaged synthetic no-egress
  smoke test with 4 sources, 4 documents, 4 entities, 3 assertions, and 1 open issue. The release
  workflow builds the equivalent artifact on Windows and macOS.

Coverage includes the loopback GUI session/origin/CSP controls, authenticated source switching,
picker command/path validation, same-port session rotation, isolated picker workspaces, and full
GUI-triggered incremental indexing with provenance. It also covers module registration, disable,
dependencies, policy blocking before initialization, event failure isolation, private state modes,
multiple source instances, checksummed incremental discovery, symlink/special-file handling, all
parser contracts, parser replacement, conflict provenance, changed/deleted/restored generations,
failed-change rollback, processing invalidation, explicit-ID separation, read-only facades, and no
socket attempts by built-ins.
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
```

The first index run reports 4 new/parsed documents, 4 entities, 3 assertions, 1 issue, and no
failures. `inspect` shows both:

```text
Freezer-001 located_in Room A-101
  equipment.xlsx / Assets / D2

Freezer-001 located_in Room A-102
  SOPs/SOP_freezers.docx / paragraph 2
```

It also shows one `CONFLICTING_LOCATION` issue referencing both assertion IDs. Running the same
`index` command again reports 4 unchanged documents and parses 0 documents.

For another folder, omit `--source-id` to derive a stable ID from the canonical root:

```bash
smart-lab-index index /path/to/read-only/lab-folder --no-egress
smart-lab-index status
```

## Current Limitations

- This is a modular foundation, not a production release for confidential laboratory data.
- The graphical UI is a local single-user operator workspace. It does not provide multi-user
  authentication, access control, editable review decisions, or source-permission enforcement.
  Permission metadata is retained but not applied to queries.
- Standalone archives are unsigned. Windows and macOS use built-in platform folder dialogs; Linux
  requires `zenity`, `kdialog`, or `yad` from the desktop environment.
- Only the filesystem connector and one broad general-lab domain pack exist.
- Extraction rules cover configured table shapes and a narrow deterministic text relation; they are
  not general document understanding.
- Search, review workflows, source-authority projection, configurable terminology, export modules,
  local inference, embeddings, semantic search, OCR, and vendor connectors are absent.
- Parsers run in-process without CPU/time/memory/page/expanded-archive limits. Do not index hostile
  or untrusted document trees yet.
- SQLite content is owner-restricted but plaintext. Use encrypted storage and a dedicated OS account
  for controlled evaluation.
- The distribution still has the compatibility identity `pdf-agent-mcp` 0.4.0. Do not publish this
  branch as that already-released version; select and validate a Smart Lab Index release identity.
- Dynamic third-party installation is intentionally absent. Built-in module boundaries are ready;
  a plugin marketplace is not.

## Next Iteration

Implement **production ingestion-boundary hardening**: execute each parser in a bounded local worker
with strict byte/page/row/cell/expanded-archive, CPU, memory, timeout, temporary-file, and output
limits; preserve bounded parser-failure issues; and verify the packaged artifact under socket-denied
no-egress tests. This is the single highest-value next step because confidential lab pilots should
not begin until malformed or hostile source documents cannot exhaust or escape the indexing process.

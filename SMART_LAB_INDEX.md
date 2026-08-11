# Smart Lab Index

Smart Lab Index builds a local knowledge index above the files and systems a laboratory already
uses. Point it at a folder and it discovers supported files, extracts entities and relationships,
keeps the exact evidence for every observed fact, and reports contradictions. It never edits the
source files.

The first foundation is deterministic. It does not require AI, a cloud service, telemetry, a vector
database, or a network connection.

## Try the graphical app

From the repository root:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/smart-lab-index-app examples/smart_lab_index/sample_lab \
  --database .smart-lab-index-demo.db --source-id lab-alpha --no-egress
```

The browser opens locally. Select **Index now**, then open the Review queue to inspect the deliberate
location conflict and its exact spreadsheet/Word evidence.

For the equivalent CLI flow:

```bash
.venv/bin/smart-lab-index index examples/smart_lab_index/sample_lab \
  --database .smart-lab-index-demo.db --source-id lab-alpha --no-egress
.venv/bin/smart-lab-index inspect --database .smart-lab-index-demo.db
```

The fixture deliberately says that `Freezer-001` is in `Room A-101` in `equipment.xlsx` and in
`Room A-102` in a Word procedure. Smart Lab Index stores both `located_in` assertions, preserves the
sheet/row or paragraph evidence, and creates one `CONFLICTING_LOCATION` issue.

The synthetic Office files are checked in. `scripts/generate_smart_lab_example.py` regenerates them
deterministically when needed. Run the same `index` command again. All four sources are reported as
unchanged and no files are parsed again.

Installed packages expose the shorter equivalent command:

```bash
smart-lab-index index /path/to/read-only/lab-folder --no-egress
```

By default, durable state is stored at `~/.smart-lab-index/index.db`. Core rejects a database path
inside the indexed source root.

## Commands

| Command | Purpose |
|---|---|
| `smart-lab-index-app ROOT` | Open the local graphical operator workspace |
| `index ROOT` | Recursively discover and incrementally index supported files |
| `status` | Show source, document, entity, assertion, issue, and latest-run counts |
| `inspect` | Return entities, assertions, provenance, and issues as JSON |
| `modules ROOT` | Show installed/enabled state, health, versions, dependencies, configuration, and security declarations |

Use repeatable `--disable MODULE_ID` options to assemble a smaller built-in profile. Dependencies
are checked before modules start.

## Architecture

Smart Lab Index is one deployable modular monolith:

```text
CLI / local capability-aware UI
              |
              v
Smart Lab Core
  identity, sources, documents, assertions, provenance
  issues, index runs, audit, module registry, event hooks
              |
              v
Enabled modules
  connectors -> parsers -> extractors -> resolvers -> issue rules
```

Core owns the SQLite database and all durable writes. Connector modules return normalized source
records and read-only byte streams. Parser modules return normalized document structures. Extractor
and issue modules return candidates or drafts. They do not overwrite Core state or write directly to
the database.

A connector provider is installed once, while each configured root is a separate immutable source
instance. Core binds each source ID to connector identity so the same ID cannot later point at a
different root. This allows one filesystem connector module to serve many laboratory folders without
duplicating module registrations.

Events are synchronous post-commit hooks. A failing hook is isolated and recorded as an audit event;
it is not a distributed message system.

## Core model

The initial universal entity types are `ORGANIZATION`, `ORGANIZATIONAL_UNIT`, `LOCATION`, `ASSET`,
`PERSON`, `DOCUMENT`, `PROCESS`, and `SOURCE_SYSTEM`. Laboratory-specific concepts such as freezer,
centrifuge, room, and laboratory are subtypes supplied by domain packs, not separate Core tables.

Assertions retain:

- subject, predicate, object or literal;
- source record and structural provenance;
- confidence and extraction method;
- assertion status;
- extraction module ID and version;
- source checksum and index-run generation.

Observed assertions are never silently replaced by another source. A changed or deleted source
supersedes its old generation while retaining history.

Document processing is tracked separately from parsing. The processing ledger records parser,
extractor, resolver, and domain versions plus redacted configuration/context hashes. An affected
document is reprocessed when one of those inputs changes. Each extractor generation is transactional:
a failure rolls back partial entities and assertions, and a changed file that cannot be parsed keeps
the last successful knowledge active.

## Built-in modules

All first-iteration modules are version `0.1.0`.

| Module | Purpose | Dependencies | Network | Files |
|---|---|---|---|---|
| `connector.filesystem` | Recursive, incremental, read-only discovery | None | None | Read source root |
| `parser.pdf` | Normalized PDF text and tables | None | None | None; receives a stream |
| `parser.docx` | Normalized Word paragraphs and tables | None | None | None; receives a stream |
| `parser.xlsx` | Normalized workbook sheets and cells | None | None | None; receives a stream |
| `parser.csv` | Normalized CSV rows and cells | None | None | None; receives a stream |
| `parser.txt` | Normalized plain-text blocks | None | None | None; receives a stream |
| `domain.general_lab` | Broad terminology and data-driven deterministic rules | None | None | None |
| `extractor.structured` | Configured spreadsheet entity/relationship extraction | `domain.extraction_rules >= 1.0.0` | None | None |
| `extractor.rules` | Configured text relationship extraction | `domain.extraction_rules >= 1.0.0` | None | None |
| `resolver.identifier` | Exact identifier resolution | None | None | None |
| `resolver.alias` | Unique alias resolution | None | None | None |
| `resolver.normalized_name` | Unique normalized-name resolution | None | None | None |
| `issue.conflicting_location` | Multiple active locations for one subject | None | None | None |

Built-ins are registered explicitly in the composition root. There is no runtime module marketplace,
dynamic third-party code loader, microservice fleet, or hidden module-to-module import graph.

## Filesystem behavior

`connector.filesystem` currently supports `.pdf`, `.docx`, `.xlsx`, `.csv`, and `.txt`. It records
relative path, timestamp, byte size, SHA-256 checksum, content type, change token, and available
permission metadata. Checksums detect changes even if size and timestamp are restored.

Symlink files and root escapes are rejected. Individual inaccessible or malformed files become
bounded failures while remaining records continue. Core infers deletion only when the connector says
the scan completed, and it excludes paths that failed during that scan.

The connector accepts regular files only, opens with no-follow protection where the operating system
supports it, verifies the opened device/inode, reads a bounded immutable snapshot, and checks that the
snapshot matches the discovered SHA-256 before parsing. The default limit is 100 MiB per file.

## No-egress mode

Set:

```bash
export SMART_LAB_INDEX_NO_EGRESS=true
```

or pass `--no-egress`. Unknown boolean spellings abort instead of silently disabling the control.
The registry blocks enabled modules declaring configured-endpoint or internet access, telemetry, or
automatic downloads before start; explicit loopback modules remain eligible for future local
inference. Source-writing modules are rejected in every mode. All current Smart Lab Index built-ins
declare zero network access.

The retained `pdf-agent-cloud-mcp` compatibility bridge also checks this policy before reading cloud
configuration or constructing an HTTP client. There is no external fallback.

Application policy prevents accidental outbound use by built-ins. A strong adversarial no-egress
deployment must additionally deny outbound network access at the operating-system or firewall layer,
because in-process Python modules are trusted code rather than a security sandbox.

## Compatibility layer

The existing `pdf_mcp` document converter remains available. Its reusable table assessment logic is
now shared with normalized parser modules, while the new `smart_lab_index` package owns the modular
product foundation. Existing PDF/DOCX extraction commands and MCP tools remain intact during the
transition.

## Graphical interface

The local GUI exposes Overview, Equipment, Locations, People, Organizations, Responsibilities,
Documents, Review queue, Issues, Sources, and Modules. Navigation is generated from enabled module
categories and stored data. Evidence rows open a detail dialog showing source path, structural
locator, confidence, module, and issue evidence.

The app accepts one configured source root at startup, performs indexing in a background thread, and
uses thread-local SQLite connections for responsive reads. All API routes containing index data
require a random browser-session token. Mutating routes additionally require a same-origin request.
Assets are bundled and the Content Security Policy permits only same-origin resources.

## Current limitations

- The GUI source root is selected at startup; a packaged native folder picker is not implemented.
- Only a filesystem connector and one general laboratory domain pack are implemented.
- Deterministic rules cover the synthetic MVP columns and a narrow `located_in` text form; they are
  not a general natural-language understanding system.
- The GUI provides local filtering and an issue review queue, but review decisions, source-authority
  projection, configurable terminology, authentication, and source-permission enforcement are not
  implemented yet.
- Local inference, embeddings, semantic search, OCR, and vendor connectors are intentionally absent.
- Connector byte limits and per-record isolation exist, but parser subprocess/time/memory and
  expanded-archive limits still need hardening for hostile content.
- Core creates private state (`0700` directory, `0600` SQLite files), but index content is not
  application-encrypted; deployments should use encrypted local storage and a dedicated OS account.
- SQLite schema version 1 is an initial foundation, not a production migration history.
- The repository distribution is still named `pdf-agent-mcp` at version `0.4.0` to preserve the
  existing compatibility product. A distinct Smart Lab Index release identity and version must be
  chosen before publishing this branch.

See [MODULAR_ARCHITECTURE.md](MODULAR_ARCHITECTURE.md) for dependency and extension rules and
[SECURITY_NO_EGRESS_REVIEW.md](SECURITY_NO_EGRESS_REVIEW.md) for the baseline audit and remaining
security gates.

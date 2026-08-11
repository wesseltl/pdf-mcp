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
.venv/bin/smart-lab-index-app
```

Choose a folder once in the system dialog. The browser opens locally, enables no-egress mode, and
starts the first read-only scan. The app stores only the approved path and local database location in
an owner-only settings file, then reopens that workspace automatically. Incremental scans repeat every
15 minutes. **Change** returns to the chooser without requiring a terminal. Picker-created workspaces
use separate local databases so unrelated folders are not silently combined. If the operating system
has no folder-dialog helper, the app opens its own secured local folder navigator instead.

The public [request-only beta page](https://wesseltl.github.io/pdf-mcp/#beta) explains the current
scope for people. Agents can read the matching
[structured beta offer](https://raw.githubusercontent.com/wesseltl/pdf-mcp/main/beta/smart-lab-index-beta.json).

To open the included demonstration without a picker:

```bash
.venv/bin/smart-lab-index-app examples/smart_lab_index/sample_lab \
  --database .smart-lab-index-demo.db --source-id lab-alpha --no-egress
```

Open Needs review to inspect the deliberate location conflict and its exact spreadsheet/Word
evidence. Select the authoritative location or dismiss the issue with a required review note. Use
Search to find names, identifiers, document text, assertions, issues, and source paths.

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

Picker-created workspaces store durable state under `~/.smart-lab-index/workspaces/`. Explicit CLI
runs default to `~/.smart-lab-index/index.db`. Core rejects a database path inside the indexed source
root. The last approved desktop workspace is remembered in the private
`~/.smart-lab-index/desktop-settings.json` file; it contains no credentials.

For the hosted subscription/local-agent split, see
[SELF_SERVICE_ARCHITECTURE.md](SELF_SERVICE_ARCHITECTURE.md).

For a dedicated single-tenant Linux deployment, use the release gates and hardened service templates
in [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md). Controlled-production mode adds an operator
credential, scheduled incremental runs, exclusive database ownership, health probes, isolated parser
workers, verified backup/restore operations, and a hash-locked CPython 3.12/Linux x86_64 runtime.

## Commands

| Command | Purpose |
|---|---|
| `smart-lab-index-app [ROOT]` | Choose a folder graphically or open an explicit source root |
| `index ROOT` | Recursively discover and incrementally index supported files |
| `status` | Show source, document, entity, assertion, issue, and latest-run counts |
| `health` | Verify database integrity, foreign keys, journal mode, and schema compatibility |
| `inspect` | Return entities, assertions, provenance, and issues as JSON |
| `modules ROOT` | Show installed/enabled state, health, versions, dependencies, configuration, and security declarations |
| `init-operator` | Create a private operator access-key file |
| `backup` | Create and verify a consistent snapshot plus SHA-256 manifest |
| `verify-backup` | Verify backup checksum, integrity, foreign keys, and schema compatibility |
| `restore` | Restore a manifested backup offline, atomically, with a pre-restore safety backup |

Use repeatable `--disable MODULE_ID` and `--enable MODULE_ID` options to assemble a built-in profile.
`issue.missing_responsibility` is installed but disabled by default because absence is only meaningful
after the operator confirms that responsibility sources are complete. Dependencies are checked before
modules start. Source runs also accept `--max-files`, `--max-total-gb`, and repeatable `--exclude GLOB`
scope controls.

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

| Module | Purpose | Dependencies | Network | Files |
|---|---|---|---|---|
| `connector.filesystem` `0.2.0` | Bounded, incremental, read-only discovery | None | None | Read source root |
| `parser.pdf` `0.2.0` | Normalized bounded PDF text and tables | None | None | None; receives a stream |
| `parser.docx` `0.2.0` | Normalized bounded Word paragraphs and tables | None | None | None; receives a stream |
| `parser.xlsx` `0.2.0` | Normalized bounded workbook sheets and cells | None | None | None; receives a stream |
| `parser.csv` `0.2.0` | Normalized bounded CSV rows and cells | None | None | None; receives a stream |
| `parser.txt` `0.2.0` | Normalized bounded plain-text blocks | None | None | None; receives a stream |
| `domain.general_lab` `0.2.0` | Broad terminology and data-driven deterministic rules | None | None | None |
| `extractor.structured` `0.2.0` | Header-aware table entities, properties, and relationships | `domain.extraction_rules >= 1.0.0` | None | None |
| `extractor.rules` | Configured text relationship extraction | `domain.extraction_rules >= 1.0.0` | None | None |
| `resolver.identifier` | Exact identifier resolution | None | None | None |
| `resolver.alias` | Unique alias resolution | None | None | None |
| `resolver.normalized_name` | Unique normalized-name resolution | None | None | None |
| `issue.conflicting_location` | Multiple active locations for one subject | None | None | None |
| `issue.calibration_due` | Invalid and overdue calibration dates | None | None | None |
| `issue.missing_responsibility` | Assets without responsibility evidence; disabled by default | None | None | None |

Built-ins are registered explicitly in the composition root. There is no runtime module marketplace,
dynamic third-party code loader, microservice fleet, or hidden module-to-module import graph.

## Filesystem behavior

`connector.filesystem` currently supports `.pdf`, `.docx`, `.xlsx`, `.csv`, and `.txt`. It records
relative path, timestamp, byte size, SHA-256 checksum, content type, change token, and available
permission metadata. Checksums detect changes even if size and timestamp are restored.

Symlink files and root escapes are rejected. Individual inaccessible or malformed files become
bounded failures while remaining records continue. Core infers deletion only when the connector says
the scan completed, and it excludes paths that failed during that scan.

Before hashing, the connector inventories eligible metadata and fails closed if the configured scope
exceeds 10,000 files or 25 GiB by default. Operators can lower or explicitly raise those limits and
exclude path/filename globs. The connector accepts regular files only, opens with no-follow protection where the operating system
supports it, verifies the opened device/inode, reads a bounded immutable snapshot, and checks that the
snapshot matches the discovered SHA-256 before parsing. The default limit is 100 MiB per file.
POSIX runs record owner, group, mode, and effective process access. This is inventory metadata, not
source ACL enforcement; Windows, Active Directory, SharePoint, and rich network-share ACLs are not
resolved by this connector.

Every selected parser runs in a fresh spawned process. Core verifies the input size and checksum,
passes bytes rather than a source path, accepts only bounded JSON-normalized output, and terminates
the worker on cancellation or wall-clock expiry. POSIX production mode additionally requires hard
CPU and address-space limits. Python audit guards deny parser network, subprocess, and file-write
operations. The parent records a bounded parsing issue and continues when one worker fails.

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

Parser workers deny network operations, and the supplied systemd unit applies an outbound allowlist
for loopback. The module registry remains trusted application code rather than a hostile plugin
sandbox, so a strong deployment must retain the operating-system firewall/service controls.

## Compatibility layer

The existing `pdf_mcp` document converter remains available. Its reusable table assessment logic is
now shared with normalized parser modules, while the new `smart_lab_index` package owns the modular
product foundation. Existing PDF/DOCX extraction commands and MCP tools remain intact during the
transition.

## Graphical interface

The local GUI exposes Overview, Search, Equipment, Locations, People, Teams, Responsibilities,
Documents, Review queue, Sources, and System health. Navigation is generated from enabled module
categories and stored data. Overview includes a connected map of indexed entities and relationships
plus a focused review action for the highest-priority open finding. Evidence rows open a detail drawer
showing source path, structural locator, confidence, module, and issue evidence. Search is server-side
and bounded, so it covers the whole SQLite index even when large list views return only their first
500 rows.
Conflict review keeps all original assertions. It marks selected evidence confirmed and alternatives
rejected, records a review decision and audit event, and reopens when materially new assertion evidence
appears.

Indexing has explicit preflight, discovery, processing, and finalization phases. The GUI shows counts,
bytes, and the current path, and cancellation stops cooperatively at the next file boundary. A
cancelled partial run never infers deletions or runs issue finalization.

The app accepts an explicit source root or opens a folder chooser. A source change performs a
controlled same-port restart, rotates the browser-session token, and reloads only after the new
session is available. Indexing runs in a background thread and SQLite connections remain thread
local. All API routes containing index data require a random browser-session token. Mutating routes
additionally require the exact loopback origin and port. Assets are bundled and the Content Security
Policy permits only same-origin resources.

Controlled-production mode additionally requires a private operator key before serving the page,
disables source switching, runs once at startup, and repeats incremental indexing every 15 minutes by
default. Minimal `/healthz` and `/readyz` endpoints expose no indexed content. The server remains
loopback-only; remote operators use an SSH tunnel instead of exposing its HTTP port.

Folder selection uses fixed local system commands without a shell: PowerShell on Windows,
`osascript` on macOS, and `zenity`, `kdialog`, or `yad` when available on Linux. If no system dialog
is available, a bundled loopback folder navigator provides the same workflow without an extra
package or terminal. Its authenticated API lists directory names only; it does not read or copy file
contents.

## Current limitations

- Standalone artifacts are ZIP applications rather than native OS installers. Builds are unsigned
  unless publisher signing credentials are configured; every archive includes a SHA-256 manifest.
- Only a filesystem connector and one general laboratory domain pack are implemented.
- Deterministic rules recognize common equipment, room, people, responsibility, serial/model/status,
  calibration, and maintenance headers plus a narrow `located_in` text form. They are not general
  natural-language understanding and customer mappings still require configuration work.
- The GUI is a local single-tenant operator workspace. Production mode has one shared operator
  credential, not named users, role-based access control, or source-permission enforcement.
- Local inference, embeddings, semantic search, OCR, and vendor connectors are intentionally absent.
- Parsers have a disposable process boundary and resource limits, but the product is not a malware
  analysis sandbox. Index only organization-approved source scopes.
- Core creates private state (`0700` directory, `0600` SQLite files), but index content is not
  application-encrypted; deployments should use encrypted local storage and a dedicated OS account.
- SQLite schema version 2 includes one tested forward migration. Back up and verify before every
  application upgrade; long migration history and automated downgrade are not available.
- The repository distribution is still named `pdf-agent-mcp` at version `0.7.0` to preserve the
  existing compatibility product. A distinct Smart Lab Index release identity and version must be
  chosen before publishing this branch.
- The hash-verified runtime lock covers CPython 3.12 on Linux x86_64 only. Other production targets
  require their own generated lock, vulnerability audit, and installation test.

See [MODULAR_ARCHITECTURE.md](MODULAR_ARCHITECTURE.md) for dependency and extension rules and
[SECURITY_NO_EGRESS_REVIEW.md](SECURITY_NO_EGRESS_REVIEW.md) for the baseline audit and remaining
security gates.

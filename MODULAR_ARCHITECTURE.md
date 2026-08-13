# LabOverlay Modular Architecture

Status: Lead-approved and implemented for foundation version `0.1.0`

Scope: first LabOverlay foundation iteration

Repository baseline: `pdf-agent-mcp` 0.4.0, Python 3.10+, no durable database

## 1. Decision Summary

Build LabOverlay as one Python modular monolith with three clear layers:

1. A small `smart_lab_index.core` package owns durable knowledge concepts, module contracts,
   orchestration policy, configuration policy, and repository interfaces.
2. Built-in capability modules implement connectors, parsers, extractors, resolvers, relationship
   extraction, issue rules, search, and optional inference.
3. Composition roots create the registry, SQLite repositories, enabled modules, and user-facing
   adapters. They are the only code allowed to import both Core implementations and concrete modules.

The current `pdf_mcp` package remains operational during migration. Its tested PDF/DOCX algorithms
are first wrapped by parser modules and only moved after compatibility tests pass. The first iteration
does not need dynamic plugin installation, entry-point discovery, a dependency-injection framework,
microservices, or an AI provider.

The dependency rule is:

```text
CLI / Web / MCP
       |
       v
Application services / composition root
       |
       v
Core contracts, domain, and repository ports
       ^
       |
Built-in modules and SQLite adapters
```

Core never imports a module implementation. Modules may import only public Core contracts and domain
value objects. A module must not import another module. Cross-capability composition is performed by
the application service or by explicit typed constructor injection in the composition root.

## 2. Current Repository Basis

The repository is small and has useful deterministic document-processing behavior, but it has no
module system or durable knowledge index yet.

| Current area | Useful behavior | Coupling to address |
|---|---|---|
| `pdf_mcp/extractor.py` | PDF text/tables, page and cell coordinates, warnings, multipage heuristic | Reads paths directly; access policy is an import-time global; includes private helpers reused elsewhere |
| `pdf_mcp/docx_extractor.py` | DOCX paragraphs/tables and cell positions | Imports PDF-private `_assess` and `_check_path` helpers |
| `pdf_mcp/exporter.py` | PDF/DOCX dispatch and XLSX/CSV/JSON export | Selects concrete parser by extension and calls parser implementation directly |
| `pdf_mcp/profiles.py` | Versioned deterministic extraction configuration | Uses the PDF module's private path guard |
| `pdf_mcp/verified.py` | Profile matching, typed records, evidence, review decisions, fingerprints | Combines document loading, parser dispatch, extraction, validation, issue creation, audit, and export |
| `pdf_mcp/server.py` | Local MCP tools | Imports and exposes every concrete implementation directly |
| `pdf_mcp/web_app.py` | Loopback-only local UI, temporary files, session protection | Calls the concrete exporter and PDF page counter directly; state is conversion-specific and in memory |
| `pdf_mcp/cloud_client.py` | Explicit hosted processing | Makes external requests and therefore cannot be part of a no-egress default runtime |
| `pdf_mcp/output_safety.py` | Spreadsheet formula defense | Reusable by a future export module, not a Core concern |

The committed baseline has no SQLite usage, migration mechanism, entity model, assertion store,
source inventory, index-run ledger, or module registry. This allows the new persistence boundary to
be introduced cleanly without migrating an existing database.

No customer-specific production behavior was found in the Python package. The `lab-coa-v1` template
is a generic example. `evaluations/simulated-customer` is explicitly fictional and contains
Northstar Water example data; it must remain test/evaluation material and must not become Core or
domain-pack defaults. Seller and payment metadata also remain outside LabOverlay runtime logic.

### Lead integration outcome

The worktree was clean at the start of the audit. The Lead reconciled the concurrent Core scaffold
before capability modules depended on it. The implemented contracts now use these decisions:

- parsers receive a path-safe `DocumentSource` plus an immutable read-only byte stream;
- one connector provider serves separately configured `SourceDefinition` instances;
- Core infers deletion only after a complete scan and excludes failed paths;
- source generations and a version/configuration processing ledger control incremental re-indexing;
- capabilities and module releases are versioned independently;
- lifecycle, health, enabled state, and policy blocking are recorded separately;
- no-egress permits only declared `NONE` or explicit `LOOPBACK` network scope and blocks telemetry
  and automatic downloads;
- issue modules return `IssueDraft` values and resolvers/issue rules receive narrow read-only facades;
- the registry records actual start order, reverses it on stop, and exposes redacted configuration;
- Core alone owns SQLite transactions and durable mutations.

These decisions are covered by focused contract and regression tests. Dynamic external plugin
loading remains deliberately out of scope; built-ins are composed explicitly.

## 3. First-Iteration Scope

The first iteration establishes real boundaries and one end-to-end deterministic indexing path:

```text
connector.filesystem
  -> parser selected by media type
  -> normalized DocumentContent
  -> deterministic extraction modules
  -> resolver chain
  -> assertions with provenance
  -> issue modules
  -> Core-owned SQLite index
```

It should include the Core, registry, SQLite storage, filesystem connector, parser adapters for the
safe existing PDF and DOCX behavior, simple XLSX/CSV/TXT parsers, structured/rule extraction,
deterministic resolution, basic issues, and synthetic tests. It should not include dynamic plugin
installation, local AI, semantic search, vendor connectors, permission enforcement, source write-back,
or licensing.

## 4. Proposed Package Shape

Add a new product package while retaining `pdf_mcp` as a compatibility package during migration:

```text
smart_lab_index/
    __init__.py
    application/
        bootstrap.py
        indexing.py
        queries.py
    core/
        domain.py
        documents.py
        contracts.py
        modules.py
        registry.py
        configuration.py
        events.py
        errors.py
        repositories.py
    infrastructure/
        sqlite/
            database.py
            migrations/
            repositories.py
        content.py
        clock.py
    modules/
        connectors/
            filesystem/
        parsers/
            common/
            pdf/
            docx/
            xlsx/
            csv/
            text/
        extractors/
            structured/
            rules/
        resolvers/
            identifier/
            alias/
            normalized_name/
        relationships/
            structured/
        issues/
            parser_failure/
            conflicting_location/
            conflicting_responsibility/
            duplicate_entity/
            missing_responsibility/
        search/
            entity/
            lexical/
        domains/
            general_lab/
    web/
    cli.py

pdf_mcp/                         # compatibility surface during migration
tests/
    core/
    modules/
    integration/
```

Each built-in module is a small package because it may contain a manifest, implementation,
configuration validation, tests, and documentation. Shared parser mechanics such as table-quality
assessment may live in `modules/parsers/common`; they do not belong in Core because Core does not
interpret PDF, Word, or table layouts.

`application/bootstrap.py` is the composition root. It imports Core, SQLite adapters, and concrete
module factories, registers the shipped modules explicitly, and returns application services. No
other file should act as a second registry or service container.

## 5. Core Boundary

### Core owns

- Universal entity identity and canonical entity types.
- Entity aliases and subtype identifiers.
- Sources, normalized source records, document versions, and source lifecycle state.
- Assertions, relationships, provenance, assertion status, and resolved-value projections.
- Issues, review decisions, audit events, and index runs.
- Typed module, connector, parser, extraction, resolution, issue, search, and inference contracts.
- Module manifests, enabled state, lifecycle state, health reports, dependency checks, and capability
  routing.
- Configuration loading/validation policy and no-egress enforcement policy.
- The in-process event dispatcher and definitions of Core events.
- Indexing phase order, transactions, failure policy, idempotency rules, and repository ports.
- SQLite schema and migrations through Core-owned infrastructure adapters.

### Core does not own

- Filesystem traversal, SMB, SharePoint, LIMS, QMS, ELN, or vendor API behavior.
- PDF, DOCX, XLSX, CSV, TXT, image, OCR, or email parsing.
- Laboratory equipment dictionaries, room conventions, document classifications, or customer terms.
- Header matching, regex extraction, fuzzy matching algorithms, embeddings, or model prompts.
- Ollama, llama.cpp, cloud AI, hosted extraction, or HTTP client implementations.
- UI navigation for optional capabilities.
- XLSX/CSV exports or spreadsheet formatting.

### Application layer owns

Application services coordinate Core ports and module capabilities. They may choose a parser, invoke
an ordered resolver chain, commit a document transaction, and publish events. They contain no PDF,
filesystem, laboratory subtype, or vendor-specific logic.

### Infrastructure owns

SQLite connection handling, secure temporary content materialization, OS clock/ID implementations,
and local HTTP serving are adapters. Infrastructure implements Core ports; it does not define domain
rules.

## 6. Universal Domain Model

Use immutable dataclasses and string-valued enums at module boundaries. Core database records may be
mapped to mutable persistence objects internally, but those must not leak to modules.

Canonical Core entity types are:

```text
ORGANIZATION
ORGANIZATIONAL_UNIT
LOCATION
ASSET
PERSON
DOCUMENT
PROCESS
SOURCE_SYSTEM
```

Modules add namespaced subtypes such as `domain.general_lab:freezer` under `ASSET`; they do not add a
`freezers` table. Location structure is represented by assertions such as a registered `parent_of`
predicate and never by fixed site/building/floor/room columns.

Recommended first public value objects are conceptually:

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping, NewType

EntityId = NewType("EntityId", str)
SourceId = NewType("SourceId", str)
SourceRecordId = NewType("SourceRecordId", str)
DocumentVersionId = NewType("DocumentVersionId", str)
AssertionId = NewType("AssertionId", str)
IndexRunId = NewType("IndexRunId", str)


class EntityType(str, Enum):
    ORGANIZATION = "ORGANIZATION"
    ORGANIZATIONAL_UNIT = "ORGANIZATIONAL_UNIT"
    LOCATION = "LOCATION"
    ASSET = "ASSET"
    PERSON = "PERSON"
    DOCUMENT = "DOCUMENT"
    PROCESS = "PROCESS"
    SOURCE_SYSTEM = "SOURCE_SYSTEM"


class AssertionStatus(str, Enum):
    DIRECT = "DIRECT"
    INFERRED = "INFERRED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CONFLICTED = "CONFLICTED"
    SUPERSEDED = "SUPERSEDED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class StructuralReference:
    # Examples: page/bbox, sheet/row/column, paragraph, JSON pointer.
    kind: str
    coordinates: Mapping[str, object]


@dataclass(frozen=True)
class Provenance:
    source_record_id: SourceRecordId
    document_version_id: DocumentVersionId | None
    structural_reference: StructuralReference | None
    module_id: str
    module_version: str
    method: str
    method_version: str
    observed_at: datetime


@dataclass(frozen=True)
class AssertionDraft:
    subject_id: EntityId
    predicate: str
    object_id: EntityId | None
    literal: object | None
    confidence: float
    status: AssertionStatus
    provenance: Provenance
    attributes: Mapping[str, object] = field(default_factory=dict)
```

Exactly one of `object_id` and `literal` is set. Confidence is between 0 and 1 and is evidence, not a
permission to overwrite another assertion. One observed fact from two sources creates two assertions.
Core computes a deterministic assertion fingerprint so re-indexing the same source generation with
the same module/method versions is idempotent.

Entity aliases are first-class, provenance-bearing records. Name normalization is versioned by the
resolver module that produced it. Core stores the original alias and normalized form; it does not
define customer-specific normalization rules.

Resolved current values are projections over assertions. They refer to the assertions and authority
policy used to derive them. Updating a projection never deletes or edits the supporting observations.
Source-authority configuration is data, scoped by predicate/entity type, and is not hardcoded in Core.

## 7. Normalized Document Contract

All parsers return one `DocumentContent` structure. It must preserve meaningful structure without
requiring every format to fabricate pages or sheets:

```python
@dataclass(frozen=True)
class ContentDiagnostic:
    code: str
    message: str
    severity: str
    reference: StructuralReference | None = None


@dataclass(frozen=True)
class TextBlock:
    text: str
    kind: str                    # paragraph, heading, page_text, cell_note
    reference: StructuralReference
    heading_level: int | None = None


@dataclass(frozen=True)
class TableCell:
    text: str
    row: int
    column: int
    reference: StructuralReference


@dataclass(frozen=True)
class DocumentTable:
    index: int
    cells: tuple[TableCell, ...]
    row_count: int
    column_count: int | None
    reference: StructuralReference
    attributes: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentContent:
    text_blocks: tuple[TextBlock, ...]
    tables: tuple[DocumentTable, ...]
    metadata: Mapping[str, object]
    diagnostics: tuple[ContentDiagnostic, ...]
```

References are format-neutral containers with format-specific coordinates. Examples are
`{"page": 7, "bbox": [...]}`, `{"sheet": "Assets", "row": 42, "column": 3}`, and
`{"paragraph": 8}`. Extractors copy these references into assertion provenance rather than reducing
them to human-readable strings.

The current PDF `cell_provenance`, page, table index, and bounding boxes map directly to this model.
The current DOCX paragraph/table indexes map directly but should use a DOCX-specific reference kind.

## 8. Module Manifest and Lifecycle

Module metadata is a typed Python object shipped with the module. It is not executable YAML and does
not require package scanning.

```python
class ModuleType(str, Enum):
    CONNECTOR = "connector"
    PARSER = "parser"
    CLASSIFIER = "classifier"
    EXTRACTOR = "extractor"
    RELATIONSHIP = "relationship"
    RESOLVER = "resolver"
    ISSUE = "issue"
    INFERENCE = "inference"
    EMBEDDING = "embedding"
    SEARCH = "search"
    DOMAIN = "domain"
    EXPORT = "export"
    UI = "ui"


class NetworkScope(str, Enum):
    NONE = "none"
    LOOPBACK = "loopback"
    CONFIGURED_ENDPOINTS = "configured_endpoints"
    INTERNET = "internet"


@dataclass(frozen=True)
class CapabilityDeclaration:
    name: str                    # e.g. parser.document, connector.source
    contract_version: int
    priority: int = 100
    attributes: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityRequirement:
    name: str
    minimum_contract_version: int
    maximum_contract_version_exclusive: int
    optional: bool = False


@dataclass(frozen=True)
class SecurityDeclaration:
    network: NetworkScope
    reads_source_files: bool
    writes_source_files: bool
    writes_managed_storage: bool
    credential_names: tuple[str, ...] = ()
    spawns_processes: bool = False
    automatic_downloads: bool = False
    telemetry: bool = False


@dataclass(frozen=True)
class ModuleManifest:
    module_id: str
    name: str
    version: str
    module_type: ModuleType
    description: str
    core_api_version: int
    capabilities: tuple[CapabilityDeclaration, ...]
    requirements: tuple[CapabilityRequirement, ...]
    configuration_fields: tuple["ConfigurationField", ...]
    security: SecurityDeclaration
```

Module IDs are lowercase, stable, and namespaced by category, for example
`connector.filesystem`, `parser.pdf`, and `domain.general_lab`. A module version follows semantic
versioning for release/audit display. Compatibility is enforced by integer Core/capability contract
versions, not by parsing arbitrary package-version ranges. A breaking contract increments its integer
version and may coexist with an older adapter during migration.

Lifecycle and health are separate:

```text
Lifecycle: REGISTERED, DISABLED, BLOCKED, INITIALIZED, STARTED, STOPPED, ERROR
Health:    HEALTHY, DEGRADED, MISCONFIGURED, UNAVAILABLE, ERROR, UNKNOWN
```

`DISABLED` and `BLOCKED` are lifecycle states, not misleading health results. `BLOCKED` includes a
machine-readable reason such as `NO_EGRESS`, `MISSING_CAPABILITY`, or `INCOMPATIBLE_CORE_API`.

The minimum lifecycle protocol is:

```python
class Module(Protocol):
    @property
    def manifest(self) -> ModuleManifest: ...

    def validate_configuration(
        self, configuration: Mapping[str, object]
    ) -> tuple["ConfigurationProblem", ...]: ...

    def initialize(
        self, context: "ModuleContext", configuration: Mapping[str, object]
    ) -> None: ...

    def start(self) -> None: ...
    def health_check(self) -> "HealthReport": ...
    def stop(self) -> None: ...
```

Stateless modules use no-op `initialize`, `start`, and `stop` implementations and return `HEALTHY`.
The context exposes only logging, a clock, temporary-content policy, an event publisher, and the
effective security policy. It does not expose a raw SQLite connection or a global bag of services.

## 9. Typed Connector Contract

Connector discovery is read-only. There is deliberately no `update`, `delete`, or `write_back` method.

```python
@dataclass(frozen=True)
class PermissionMetadata:
    raw: Mapping[str, object]
    complete: bool


@dataclass(frozen=True)
class SourceSnapshot:
    external_id: str
    modified_at: datetime | None
    size_bytes: int | None
    checksum: str | None
    change_token: str | None


@dataclass(frozen=True)
class DiscoveredSourceRecord:
    external_id: str
    name: str
    locator: str
    content_type: str | None
    modified_at: datetime | None
    size_bytes: int | None
    checksum: str | None
    change_token: str | None
    metadata: Mapping[str, object]
    permissions: PermissionMetadata | None
    content_reference: Mapping[str, object]


@dataclass(frozen=True)
class DiscoveryFailure:
    external_id: str | None
    locator: str
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class DiscoveryRequest:
    source_id: SourceId
    previous: Mapping[str, SourceSnapshot]


DiscoveryItem = DiscoveredSourceRecord | DiscoveryFailure


class Connector(Module, Protocol):
    def discover(self, request: DiscoveryRequest) -> Iterable[DiscoveryItem]: ...

    def open_content(
        self, record: DiscoveredSourceRecord
    ) -> ContextManager[BinaryIO]: ...
```

The Core/application service supplies prior snapshots. A connector may reuse a prior checksum when
its trustworthy change token is unchanged, but every new or changed file must receive a checksum.
`connector.filesystem` uses a stable normalized path relative to its configured root as
`external_id`; the absolute path remains protected source metadata/content reference.

Per-record access errors are yielded as `DiscoveryFailure` and do not stop iteration. If iteration
itself raises, the scan is incomplete. Core must not infer deletions from an incomplete scan. Only
after normal completion does Core mark previously active records not seen in the run as deleted.
Deletion is an observation: source history and old assertions are retained.

`open_content` must open the source read-only. The application service owns stream lifetime and passes
the stream only to the selected parser. Future connectors may materialize remote content into a
Core-managed temporary file, but the source record still points to the authoritative external source.

## 10. Typed Parser Contract

Parser routing uses manifest capability attributes such as MIME types and filename suffixes. Parser
code receives a seekable binary stream, not authority to locate arbitrary files.

```python
@dataclass(frozen=True)
class ParseRequest:
    source_record_id: SourceRecordId
    name: str
    content_type: str | None
    checksum: str
    content: BinaryIO


class Parser(Module, Protocol):
    def parse(self, request: ParseRequest) -> DocumentContent: ...
```

The manifest for `parser.pdf` declares, for example:

```text
capability: parser.document, contract_version 1
attributes: media_types=[application/pdf], suffixes=[.pdf]
network: none
reads_source_files: false
```

The parser reads only the stream supplied by Core. The existing libraries accept file-like input; if
one later requires a path, Core's content service may provide a private, bounded temporary path under
an explicit context manager. A parser must not create unmanaged temporary files.

Parser selection is deterministic:

1. An explicit source/parser override, if configured and compatible.
2. Exact content type match.
3. Filename suffix match.
4. Lowest configured priority number.
5. Module ID as a stable tie-breaker.

Ambiguous matches at the same effective rank produce an issue/configuration error rather than
nondeterministic selection. Parser failure raises a bounded `ParserError` containing an error code and
safe message; the orchestrator records `PARSING_FAILURE` and continues with the next document.

## 11. Other Capability Contracts

Keep additional contracts narrow and result-oriented:

```text
Classifier.classify(DocumentContext) -> sequence[ClassificationEvidence]
EntityExtractor.extract(DocumentContext) -> sequence[EntityCandidate]
RelationshipExtractor.extract(DocumentContext, EntityBindings) -> sequence[AssertionCandidate]
Resolver.propose(EntityCandidate, EntityLookup) -> ResolutionProposal
IssueRule.evaluate(IssueContext) -> sequence[IssueDraft]
SearchProvider.search(SearchQuery, AccessContext) -> SearchResultPage
InferenceProvider.structured_inference(InferenceRequest) -> ValidatedStructuredResponse
EmbeddingProvider.embed(EmbeddingRequest) -> EmbeddingBatch
```

Extractors and relationship modules return candidates/drafts. They never write entities or
assertions. Resolvers return proposals with evidence and confidence. Core application services apply
configured thresholds and persist the decision. Issue rules return idempotent drafts; Core owns issue
deduplication and status transitions.

The first iteration does not implement `InferenceProvider` or `EmbeddingProvider`; defining their
ports prevents later Ollama or embedding choices from leaking into Core business logic.

## 12. Registry and Capability Rules

The first registry is an in-memory object populated from an explicit built-in module list in
`application/bootstrap.py`. It provides:

- `register(module)` with duplicate ID rejection.
- Manifest and Core API validation.
- Enabled/disabled and no-egress checks.
- Required capability validation.
- Cycle detection over required capabilities after providers are selected.
- Deterministic lifecycle start order and reverse stop order.
- Provider queries by capability, contract version, and manifest attributes.
- Current lifecycle and health snapshots for the UI and index-run audit.

Installed means "shipped and registered in this process." Enabled means selected in configuration.
No runtime `pip install`, directory import, arbitrary Python path, or package entry-point discovery is
needed for the first iteration. A trusted external-plugin loader may be added later without changing
the contracts, once installation, signing/trust, schema migration, and support policy are defined.

Capability requirements are preferred over module-ID dependencies. For example, a future semantic
search module requires `embedding.provider` contract version 1, not
`embedding.local_sentence_transformer`. An exact module-ID requirement is permitted only when the
dependency is genuinely implementation-specific and must be explained in the module documentation.

Multiple providers are normal for parsers, classifiers, extractors, resolvers, and issue rules.
Cardinality and ordering belong to the application pipeline configuration:

- Connector: exactly one provider per configured source.
- Parser: exactly one selected per document.
- Classifier/extractor/relationship/issue: zero or many, invoked in stable configured order.
- Resolver: zero or many, invoked as a staged chain.
- Inference/embedding: zero or one selected provider per named task/profile.
- Search: one provider per requested search mode; hybrid search may compose typed search ports.

A module cannot satisfy its own required capability unless the manifest explicitly declares that
capability and the composition does not create a lifecycle cycle.

## 13. Configuration Strategy

Use one local TOML file, parsed with Python's standard `tomllib`, plus narrowly defined environment
overrides:

```toml
[core]
database_path = "./laboverlay.sqlite3"
no_egress = true

[sources.lab_alpha]
connector = "connector.filesystem"
name = "Lab Alpha files"

[sources.lab_alpha.configuration]
roots = ["./sample_lab"]
follow_symlinks = false

[modules."parser.pdf"]
enabled = true

[modules."parser.docx"]
enabled = true

[modules."inference.ollama"]
enabled = false
```

Customer variation is represented by enabled modules, source instances, module configuration,
authority policy, terminology, and domain packs. It is never represented by a customer fork or an
`if customer_name == ...` branch.

Each manifest declares simple typed `ConfigurationField` entries: name, type, required/default,
bounds or allowed values, secret flag, and description. Core validates unknown fields and types before
module initialization; a module performs semantic validation such as checking that a root is readable.
This intentionally avoids adding a full JSON Schema runtime in the first iteration while retaining
enough metadata for a future settings UI. A JSON Schema export can be generated later from these
fields.

Environment variables are for deployment policy and secret references, not an alternative hidden
configuration system. Reserve:

```text
LABOVERLAY_CONFIG
LABOVERLAY_DATABASE
LABOVERLAY_NO_EGRESS
LABOVERLAY_SECRET_<NAME>
```

An invalid boolean environment value is a startup error. `LABOVERLAY_NO_EGRESS=true` overrides
the file and cannot be turned off by a module. Secrets are resolved at initialization, redacted from
logs, and never persisted in module configuration or index-run snapshots; snapshots store only secret
names and a configuration hash.

The current `PDF_MCP_ALLOWED_DIR` remains supported by compatibility commands. New source access is
configured per connector instance and enforced by the connector/content service rather than a module
global captured at import time.

## 14. No-Egress and Module Security

At startup, the registry evaluates every enabled module's `SecurityDeclaration` before initialization.
With no-egress enabled:

- `NONE` and `LOOPBACK` network scopes may be allowed.
- `CONFIGURED_ENDPOINTS` and `INTERNET` are blocked.
- Any module declaring telemetry or automatic downloads is blocked.
- A dependency on a blocked capability blocks or degrades the dependent optional module; it never
  selects an external fallback.
- Model/package/content auto-download code is not invoked.
- The effective module list and every blocked reason are recorded in the index run and module status.

Loopback is allowed so a future explicitly configured local inference process can be used without
internet access. That module must declare `LOOPBACK`, the permitted host/port configuration, process
spawning behavior, model storage, and that it performs no automatic model download. A mode stricter
than no-egress may later disable loopback too.

The current `pdf_mcp.cloud_client` and hosted MCP bridge declare external network use and must not be
registered in the default LabOverlay composition. During migration, their entry point must check
the effective no-egress policy and fail before reading a document when no-egress is true.

Built-in parsers require no network. Frontend assets must continue to be package-local, as they are in
the current `pdf_mcp.web_ui`; no runtime CDN is permitted. Telemetry remains absent by default.

Manifest enforcement is fail-closed for product-owned modules but is not an operating-system sandbox
against malicious Python. A future external-plugin feature requires a trust model, and high-assurance
air-gapped deployments should additionally enforce egress at the host firewall. The product must not
claim that Python metadata alone can contain hostile plugins.

## 15. Events and Hooks

Use a synchronous in-process event dispatcher. Do not use events to hide the main indexing control
flow: connector, parser, extractor, resolver, persistence, and issue phases remain explicit calls in
the application service.

An event envelope contains:

```text
event_id
event_type
occurred_at UTC
index_run_id
source_record_id, document_version_id, or entity_id when applicable
payload schema version
small typed payload
```

Initial events are:

```text
SOURCE_DISCOVERED
SOURCE_RECORD_CHANGED
SOURCE_RECORD_DELETED
DOCUMENT_REGISTERED
DOCUMENT_PARSED
ENTITY_CANDIDATE_FOUND
ENTITY_CREATED
ASSERTION_CREATED
ENTITY_MERGED
ISSUE_CREATED
REVIEW_COMPLETED
INDEX_RUN_COMPLETED
```

Events are published only after the transaction containing the referenced state commits. Handlers are
registered with an owner module ID and invoked in stable `(priority, module_id)` order. A handler
failure is recorded against that module and event, then processing continues unless the handler was
explicitly configured as required.

Important domain/audit events are also written to Core's `audit_events` table. The in-memory bus is a
hook mechanism, not a durable queue and not an implicit retry engine. Event payloads contain IDs and
small summaries, not entire documents or extracted text.

## 16. SQLite Ownership and Schema Direction

Core owns one SQLite database and all migrations. Use the standard `sqlite3` library initially with:

```text
PRAGMA foreign_keys = ON
PRAGMA journal_mode = WAL
PRAGMA busy_timeout = 5000
PRAGMA synchronous = NORMAL
```

The application opens connections; modules never receive a raw connection, cursor, SQL string, or
table name. Modules receive immutable inputs and return results. Resolver and issue modules that need
existing knowledge receive narrow read-only ports such as `EntityLookup` or prepared fact snapshots.
Only Core repository implementations persist module output.

Core migrations create these logical tables:

| Table group | Purpose |
|---|---|
| `schema_migrations`, `core_metadata` | Schema and Core API versions |
| `module_states` | Installed version, enabled/lifecycle/health state, safe config hash, last check |
| `sources` | Configured source instances and connector module identity/version |
| `source_records` | Current normalized external records, content reference, permissions, active/deleted/inaccessible state |
| `source_observations` | Per-run size/time/checksum/change token and discovery result history |
| `document_versions` | Immutable source checksum generation, selected parser/version, normalized content JSON, parse status |
| `entities` | Stable universal entity identity, canonical type, namespaced subtype, display name, lifecycle state |
| `entity_aliases` | Original and normalized aliases with provenance and normalizer version |
| `provenance_records` | Source/document reference, structural coordinates, producer and method versions |
| `assertions` | Subject, predicate, object or typed literal, confidence, status, provenance, idempotency fingerprint |
| `resolved_values` | Current projection plus policy/version and supporting assertion IDs; never replaces assertions |
| `issues` | Rule/module version, issue type, severity, status, subject, stable fingerprint |
| `issue_evidence` | Links issues to assertions, entities, documents, and provenance |
| `review_decisions` | Confirm/reject/merge decisions, actor label, reason, time, affected records |
| `index_runs` | Source, status, start/end, counters, effective no-egress/config hash |
| `index_run_modules` | Enabled module IDs/versions/config hashes/health and inference metadata for reproducibility |
| `module_executions` | Per-run/per-document module timing, result, bounded error code |
| `audit_events` | Append-only human/system action log with versioned, bounded JSON details |

Use opaque UUID strings generated by a Core `IdGenerator`, UTC timestamps, foreign keys, and explicit
unique indexes. Store configuration and structural metadata as canonical JSON where fields are
module-extensible. Frequently queried identity, type, status, checksum, predicate, and time fields
remain relational columns.

For the first iteration, normalized `DocumentContent` may be stored as versioned JSON in SQLite. Raw
source bytes are not copied into the index. If corpus size later makes this unsuitable, a Core-owned
content-artifact repository can move large normalized artifacts to managed files without changing
parser or extraction contracts.

Modules do not create private tables in the first iteration. A future module-storage API may provide
namespaced derived storage, but durable entities, assertions, provenance, issues, reviews, and runs
always remain Core-owned.

Transactions are bounded per document, not one transaction for an entire source scan. This permits
failure isolation and prevents a large run from holding a write lock. Run counters and final status are
updated separately. Repository methods use parameterized SQL only.

## 17. Indexing Orchestration

`IndexingService.run(source_id)` follows this explicit sequence:

1. Load the source and effective configuration; create an `index_run` with a safe configuration hash.
2. Snapshot enabled module IDs, versions, health, contract versions, and no-egress decisions into
   `index_run_modules`.
3. Resolve exactly one connector for the source and load previous source snapshots.
4. Iterate connector discovery. Upsert each source record observation and isolate yielded failures.
5. Classify records as new, changed, or unchanged using connector change token plus checksum. Queue
   only new/changed content for parsing.
6. If discovery completes normally, mark previously active unseen records as deleted. If discovery is
   incomplete, record a degraded run and do not infer deletion.
7. For each queued record, select one parser deterministically and open content through its connector.
8. Parse to `DocumentContent`. In one document transaction, persist the immutable document generation
   and parser diagnostics.
9. Invoke all enabled classifiers and entity extractors in stable order. Persist their candidates and
   evidence only through Core services.
10. Run resolvers in configured stages: exact identifier, alias, normalized name, then optional fuzzy
    candidate generation. Automatic merge thresholds are configuration; uncertain proposals enter
    review.
11. Invoke relationship modules using the resolved entity bindings. Validate registered predicates
    and persist assertion drafts with provenance and producer versions.
12. Recompute only affected resolved-value projections without changing observations.
13. Invoke enabled issue modules against the affected facts and persist idempotent issues/evidence.
14. Commit, then publish document/entity/assertion/issue events. Continue with the next record.
15. Finalize counts and status as `COMPLETED`, `COMPLETED_WITH_ERRORS`, `FAILED`, or `CANCELLED`, then
    publish `INDEX_RUN_COMPLETED`.

AI is not in this required path. A disabled or unavailable optional classifier/extractor cannot stop
structured XLSX extraction. Required connector failure may fail the source run; parser failure affects
one document; optional module failure is recorded and processing continues.

Deleted or changed source records do not cause historical assertions to be deleted. A newer document
generation can mark prior generated assertions `SUPERSEDED` for current projection purposes while
retaining them for audit. Human-confirmed assertions require an explicit review policy before any
automatic supersession.

## 18. Idempotency, Versioning, and Re-indexing

Every generated durable record includes producer module ID/version and method/schema version. Parser,
extractor, resolver, relationship, issue, prompt, model, and embedding versions are recorded when used.

Recommended fingerprints are hashes over canonical JSON:

- Source generation: source ID + external ID + content checksum.
- Document parse: source generation + parser ID/version + parser contract version + parse settings.
- Assertion: subject/object-or-literal + predicate + provenance + producer/method versions.
- Issue: rule ID/version + issue type + affected identity + evidence IDs.

The run planner can later query generations produced by an older component and schedule targeted
re-indexing. It must not silently combine incompatible parser output schemas. Contract-version changes
require an adapter, migration, or reparse.

## 19. Initial Built-in Modules

Recommended manifests for the first usable composition are:

| Module ID | Version | Capability | Core API | Security | Required capability |
|---|---:|---|---:|---|---|
| `connector.filesystem` | `0.1.0` | `connector.source@1` | 1 | source read, network none, no writes | none |
| `parser.pdf` | `0.1.0` | `parser.document@1` | 1 | supplied content only, network none | none |
| `parser.docx` | `0.1.0` | `parser.document@1` | 1 | supplied content only, network none | none |
| `parser.xlsx` | `0.1.0` | `parser.document@1` | 1 | supplied content only, network none | none |
| `parser.csv` | `0.1.0` | `parser.document@1` | 1 | supplied content only, network none | none |
| `parser.txt` | `0.1.0` | `parser.document@1` | 1 | supplied content only, network none | none |
| `extractor.structured` | `0.1.0` | `extractor.entity@1` | 1 | network none | normalized documents |
| `extractor.rules` | `0.1.0` | `extractor.entity@1` | 1 | network none | normalized documents/domain terms |
| `resolver.identifier` | `0.1.0` | `resolver.entity@1` | 1 | network none | entity lookup |
| `resolver.alias` | `0.1.0` | `resolver.entity@1` | 1 | network none | entity lookup |
| `resolver.normalized_name` | `0.1.0` | `resolver.entity@1` | 1 | network none | entity lookup |
| `relationship.structured` | `0.1.0` | `extractor.relationship@1` | 1 | network none | resolved bindings |
| `issue.parser_failure` | `0.1.0` | `issue.rule@1` | 1 | network none | none |
| `issue.conflicting_location` | `0.1.0` | `issue.rule@1` | 1 | network none | registered predicate definition |
| `domain.general_lab` | `0.1.0` | `domain.pack@1` | 1 | network none | none |
| `search.entity` | `0.1.0` | `search.provider@1` | 1 | network none | entity query port |

"Required capability" in this table is descriptive; manifests should express only actual runtime
capability dependencies. Access to a Core port such as entity lookup is a Core API requirement, not a
module dependency.

The exact issue set should be added only when its input facts and semantics are testable. For example,
`missing_responsibility` must be disabled unless a domain/configuration rule defines which entity types
require responsibility; Core must not assume every asset needs an owner.

## 20. UI Capability Model

The first LabOverlay UI calls application query/command services; it does not query SQLite or module
objects directly. Core views such as Overview, Entities, Assertions, Provenance, Sources, Issues,
Review, Index Runs, and Modules are always available when their Core service is enabled.

Optional navigation is driven by declarative capability metadata returned by the backend:

```text
view_id
label_key
route
required_capability
order
```

`domain.general_lab` may map `ASSET` to "Equipment" and add filtered Locations, Equipment, People,
Organizations, and Responsibilities views. The data remains canonical Core entities/assertions.
Terminology is configuration/localization, not a schema fork.

Do not load arbitrary module JavaScript in the first iteration. Built-in UI panels register in one
frontend view registry, and unavailable capabilities are omitted or shown as disabled in Modules.
This is enough to avoid a giant hardcoded navigation component without creating a browser plugin
framework.

## 21. Extension Rules

A future `connector.some_lims` should require only:

1. A manifest declaring `connector.source@1`, configuration, and security needs.
2. An implementation of `Connector` that yields normalized source records and failures.
3. Tests for incremental discovery, permissions, failure isolation, and no-egress behavior.
4. Explicit registration in the trusted composition root.

It must not modify entities, assertions, filesystem code, parsers, issue persistence, or SQLite schema.

A future `parser.new_format` implements `Parser`, advertises media types/suffixes, and is registered.
The orchestrator and connector remain unchanged.

A future `inference.new_local_runtime` implements `InferenceProvider`. AI task modules depend on that
typed capability and validate structured output before returning drafts. Core, deterministic
extractors, and issue persistence remain unchanged.

Additional rules:

- Public Core contracts live in a small documented namespace; modules never import `_private` Core
  implementation files.
- Core repository interfaces are use-case-specific, not a generic CRUD repository or raw SQL escape.
- Domain packs register namespaced subtype, predicate, terminology, and rule definitions; they do not
  mutate Core enums or migrations.
- A module cannot mutate another module's state or configuration.
- Source credentials are referenced by secret name and supplied only to the owning connector.
- Connectors preserve permission metadata even though first-iteration query enforcement is not yet a
  complete IAM system.
- Source files are immutable from the product's perspective. Export modules write only explicit new
  outputs outside connector interfaces.
- Circular requirements fail registry validation before any module starts.

## 22. Incremental Migration Map

### Step 0: Preserve the baseline

- Keep the existing 0.4.0 commands and 103-test behavior as regression coverage.
- Add architecture tests that enforce import direction before moving implementations.
- Treat `pdf_mcp` outputs as compatibility contracts until a versioned deprecation decision.

### Step 1: Add contracts, registry, and composition root

- Create `smart_lab_index.core` value objects, module contracts, registry, configuration, and events.
- Register a fake connector/parser in tests to prove replacement, disable/enable, dependency checks,
  lifecycle, and no-egress blocking.
- Add no database or UI behavior change in this step.

### Step 2: Wrap existing document parsers

- Implement `parser.pdf` as an adapter around `pdf_mcp.extractor` and `parser.docx` around
  `pdf_mcp.docx_extractor`.
- Map existing rows, diagnostics, pages, bounding boxes, paragraph indexes, and cell provenance to
  `DocumentContent`.
- Move `_assess` to parser-common code or duplicate a tiny stable adapter temporarily; remove the
  DOCX-to-PDF private import.
- Replace import-time `_ALLOWED_DIR` with injected content/source policy for new code while preserving
  `PDF_MCP_ALLOWED_DIR` in legacy entry points.
- Keep `exporter.py`, `server.py`, and `web_app.py` behavior unchanged through compatibility adapters.

### Step 3: Add Core-owned SQLite and domain repositories

- Add ordered transactional migrations and repositories for sources, document versions, entities,
  aliases, provenance, assertions, issues, reviews, module state, audit, and index runs.
- Add repository contract tests against a temporary SQLite database.
- Store normalized parser output but never raw source bytes.

### Step 4: Add `connector.filesystem` and indexing skeleton

- Implement recursive read-only discovery, stable relative IDs, size/time, SHA-256, inaccessible-file
  failures, changed-file reuse, and safe deletion detection after complete scans.
- Orchestrate discovery and parsing first, with per-document transactions and parser-failure issues.
- Prove a second unchanged run performs no parse and a deleted file is marked without erasing history.

### Step 5: Add deterministic formats and knowledge modules

- Add XLSX, CSV, and TXT parsers using existing dependencies/standard library where practical.
- Add structured spreadsheet extraction, general-lab rule extraction, controlled predicate
  registration, deterministic resolver stages, and narrowly defined issue rules.
- Build the synthetic `sample_lab` conflict scenario entirely offline.

### Step 6: Add LabOverlay query/UI adapters

- Add application queries for overview, entities, assertions/provenance, sources, issues, review,
  index runs, and modules.
- Introduce a new LabOverlay browser entry point backed by these services. Keep the existing converter
  entry point until its document-export use case is available as an optional module/view.
- Update MCP tools to call application services rather than concrete parsers where equivalent tools
  are retained.

### Step 7: Rehome profile and export behavior

- Split `verified.py` into an optional profile-driven structured extractor/validation issue module and
  an export module. Preserve its deterministic evidence and fingerprint behavior.
- Reuse `output_safety.py` in `export.spreadsheet`.
- Keep `cloud_client.py` as an explicitly enabled external-processing compatibility module or remove it
  from LabOverlay packaging by product decision; never make it a fallback.

### Step 8: Product rename and compatibility retirement

- Change distribution/entry-point branding only after the LabOverlay indexing path is usable.
- Publish a deprecation window for `pdf-agent-mcp` commands and retain adapters for at least one
  release if users depend on them.
- Do not combine a package rename, database introduction, and parser rewrite in one release.

## 23. First-Iteration Verification

Acceptance tests should prove:

- Core imports no module implementation and no parser/vendor library.
- Registering a second fake connector requires no Core change.
- Registering a fake parser for a new media type requires no orchestrator change.
- Modules report ID/version, enabled state, lifecycle, health, configuration problems, and security.
- A required capability mismatch/cycle fails before startup.
- A network module is blocked by no-egress, and no external fallback is selected.
- Disabling PDF parsing does not prevent CSV/XLSX indexing.
- One inaccessible file and one parser failure do not prevent other documents from committing.
- An incomplete connector scan does not mark records deleted.
- Unchanged files are not reparsed; changed files create immutable document generations.
- Entity and assertion writes are idempotent for the same generation/module versions.
- Conflicting location assertions are both retained with source cell/page provenance and create one
  conflict issue.
- Source permissions survive connector normalization and storage.
- Existing PDF/DOCX extraction/export/profile tests continue to pass where practical.
- Test fixtures contain synthetic names only and require no network, AI, telemetry, or external assets.

Add a simple import-boundary test or static rule, for example:

```text
smart_lab_index/core/** must not import smart_lab_index/modules/**
smart_lab_index/modules/<A>/** must not import smart_lab_index/modules/<B>/**
```

## 24. Deliberate Deferrals

- Dynamic third-party plugin discovery and installation.
- Module-owned database migrations/tables.
- Public plugin marketplace or signing infrastructure.
- Background worker framework or distributed event broker.
- Async conversion of the whole codebase.
- Graph database.
- Vector database, embeddings, semantic/hybrid search.
- Local or cloud inference implementation.
- Complete permission enforcement/IAM synchronization.
- Automatic write-back to any source.
- Pricing, licensing, and product-tier enforcement.

These deferrals keep the Core small and make the first modular boundary testable.

## 25. Decisions Requiring Lead Approval

1. **Package boundary:** approve a new `smart_lab_index` package beside a temporary `pdf_mcp`
   compatibility package instead of renaming/moving all existing code immediately.
2. **Registry scope:** approve explicit built-in registration only for the first iteration; defer
   Python entry points and third-party runtime loading.
3. **Contract compatibility:** approve integer Core/capability API versions and semantic module
   versions, avoiding arbitrary runtime version-range resolution.
4. **Storage:** approve one Core-owned SQLite database, no module-owned tables, normalized content as
   versioned JSON initially, and no raw source-byte ingestion.
5. **Configuration:** approve one TOML configuration with typed manifest fields and narrowly scoped
   environment overrides; avoid adding Pydantic/JSON Schema dependencies in the foundation.
6. **No-egress semantics:** approve loopback as compatible, external endpoints/telemetry/automatic
   downloads as blocked, and document that host-level controls are needed to sandbox untrusted future
   plugins.
7. **Orchestration:** approve explicit synchronous pipeline calls with post-commit in-process events,
   rather than an event-driven workflow engine.
8. **Compatibility:** approve wrapping current PDF/DOCX behavior first and deferring physical code
   moves until adapters and regression tests are stable.
9. **UI modules:** approve declarative built-in view contributions only; defer arbitrary runtime
   frontend plugins.
10. **Hosted bridge:** decide whether the existing hosted extraction bridge remains a separately
    packaged compatibility capability or is excluded from future LabOverlay distributions.

Approval of these decisions is sufficient to begin Step 1 without committing the product to
microservices, a plugin marketplace, AI, or a particular laboratory/vendor implementation.

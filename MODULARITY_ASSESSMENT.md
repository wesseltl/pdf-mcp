# Modularity Assessment

## Current maturity

The repository is a **functionally separated but architecturally coupled single package**. Files are
small enough to understand, and many functions are deterministic and tested. However, source files are
not modules in the LabOverlay sense. There is no explicit contract, manifest, registry,
configuration schema, lifecycle, health state, dependency declaration, or capability discovery.

The correct starting point remains a modular monolith. Nothing in the current scale or deployment model
justifies microservices, containers, a broker, or one database per capability.

## Current dependency direction

The important in-package dependencies are:

```text
extractor (PDF + global path policy + shared table assessment)
  ^          ^             ^
  |          |             |
docx       profiles      evaluator
  ^          ^             |
  |          |             v
  +------ verified <-------+
  |          |
  +-- exporter
         ^   ^
         |   |
        CLI  web app

server imports extractor + docx + exporter + profiles + verified
cloud server -> cloud client -> extractor._check_path
```

Concrete evidence:

- DOCX imports private `_assess` and `_check_path` helpers from the PDF implementation
  ([`pdf_mcp/docx_extractor.py:14`](pdf_mcp/docx_extractor.py#L14)).
- Profile loading imports private `_check_path` from the PDF implementation
  ([`pdf_mcp/profiles.py:12`](pdf_mcp/profiles.py#L12)).
- Cloud upload validation imports the PDF implementation for the same private path policy
  ([`pdf_mcp/cloud_client.py:9`](pdf_mcp/cloud_client.py#L9)).
- Export dispatch directly imports both parser implementations
  ([`pdf_mcp/exporter.py:13`](pdf_mcp/exporter.py#L13)).
- Verified extraction directly imports and selects both parser implementations
  ([`pdf_mcp/verified.py:17`](pdf_mcp/verified.py#L17),
  [`pdf_mcp/verified.py:390`](pdf_mcp/verified.py#L390)).
- The MCP adapter imports every concrete feature module
  ([`pdf_mcp/server.py:11`](pdf_mcp/server.py#L11)).
- The browser backend calls the concrete exporter and PDF page counter
  ([`pdf_mcp/web_app.py:21`](pdf_mcp/web_app.py#L21),
  [`pdf_mcp/web_app.py:238`](pdf_mcp/web_app.py#L238)).

This direction makes `extractor.py` an accidental infrastructure root even though it is nominally a
PDF parser.

## Core-versus-module assessment

### Candidate Core concepts already hinted at

The repository contains useful concepts but no Core implementations:

| Existing concept | Evidence | Core relevance | Limitation |
| --- | --- | --- | --- |
| File SHA-256 and byte size | [`pdf_mcp/verified.py:41`](pdf_mcp/verified.py#L41) | Source/document identity and change detection | Private, one-file, PDF/DOCX-specific helper; no change token or deletion state. |
| Cell evidence | [`pdf_mcp/extractor.py:102`](pdf_mcp/extractor.py#L102), [`pdf_mcp/docx_extractor.py:39`](pdf_mcp/docx_extractor.py#L39) | Provenance references | Shape differs by parser and lacks durable source/document IDs. |
| Versioned extraction fingerprint | [`pdf_mcp/verified.py:541`](pdf_mcp/verified.py#L541) | Reproducibility and index-run lineage | Product/profile-specific and records only one parser engine. |
| Issue dictionaries | [`pdf_mcp/verified.py:25`](pdf_mcp/verified.py#L25) | Durable issue framework | No identity, lifecycle, module owner, timestamps, review state, or persistence. |
| Review decision | [`pdf_mcp/verified.py:533`](pdf_mcp/verified.py#L533) | Human-verifiable workflow | Operation-wide profile result, not assertion/entity review. |
| Strict versioned JSON configuration | [`pdf_mcp/profiles.py:61`](pdf_mcp/profiles.py#L61) | Module/configuration validation pattern | Defines one table profile, not a global module config strategy. |

These concepts should inform Core contracts. Their current dictionaries should not be promoted directly
to database schemas.

### Responsibilities that belong in modules

| Current functionality | Future module category |
| --- | --- |
| `pdfplumber` extraction | `parser.pdf` |
| `python-docx` extraction | `parser.docx` |
| Profile schema and header matching | document-intelligence configuration plus `extractor.structured` |
| Typed profile conversion | `extractor.structured` |
| Table cleanliness checks | parser diagnostics and/or independently configurable issue rules |
| Multipage table stitching | PDF parser post-processing capability |
| XLSX/CSV/JSON writing | export modules |
| FastMCP tools | optional interface/MCP module |
| Hosted extraction client | optional network-capable integration module |
| Local browser routes and views | local UI host plus capability-provided views |
| Ground-truth evaluation | development/evaluation tooling, not runtime Core |
| Stripe and offer handling | distribution/commerce tooling, outside product Core |

## Tight-coupling findings

### 1. There is no stable domain boundary

**Severity: Critical for the LabOverlay transition.**

Current outputs are untyped nested dictionaries tailored to table conversion. There are no entities,
aliases, assertions, predicates, sources, documents, issues, index runs, review decisions, or audit
repositories. Adding these concepts inside `verified.py` or `web_app.py` would create the monolith the
new architecture is intended to avoid.

### 2. Parser dispatch is duplicated and closed to extension

**Severity: High.**

`exporter._source_type()` accepts only PDF/DOCX and directly invokes their implementations
([`pdf_mcp/exporter.py:17`](pdf_mcp/exporter.py#L17),
[`pdf_mcp/exporter.py:44`](pdf_mcp/exporter.py#L44)). `verified.extract_with_profile()` repeats that
selection ([`pdf_mcp/verified.py:394`](pdf_mcp/verified.py#L394)). Adding `parser.xlsx` currently requires
editing both orchestrators and likely every interface adapter.

### 3. Shared infrastructure is owned by the PDF parser

**Severity: High.**

Path authorization and generic table assessment are private functions in `extractor.py`, yet DOCX,
profiles, cloud upload, export, evaluation, and profile CLI rely on them. This violates dependency
inversion and makes replacing the PDF parser risky. File access policy should be a Core/infrastructure
service. Generic table diagnostics should be a parser contract utility or issue capability.

The allowed directory is also captured at import time in
[`pdf_mcp/extractor.py:15`](pdf_mcp/extractor.py#L15), preventing one process from safely supporting
multiple source configurations or reloading settings.

### 4. Verified extraction is a workflow monolith

**Severity: High.**

The 708-line `verified.py` owns:

- input validation and hashing;
- concrete parser selection;
- engine version discovery;
- header classification/matching;
- typed row extraction;
- provenance mapping;
- issue creation and deduplication;
- duplicate-key detection;
- review decision policy;
- extraction fingerprinting; and
- three output writers.

Relevant boundaries are visible at [`pdf_mcp/verified.py:41`](pdf_mcp/verified.py#L41),
[`pdf_mcp/verified.py:84`](pdf_mcp/verified.py#L84), [`pdf_mcp/verified.py:236`](pdf_mcp/verified.py#L236),
[`pdf_mcp/verified.py:390`](pdf_mcp/verified.py#L390), and
[`pdf_mcp/verified.py:587`](pdf_mcp/verified.py#L587). This is the primary component to decompose through
adapters after contracts exist, not before.

### 5. Failure isolation exists only at a request boundary

**Severity: High for recursive indexing.**

The browser catches one conversion exception and returns a bounded message
([`pdf_mcp/web_app.py:205`](pdf_mcp/web_app.py#L205)). CLI and MCP calls otherwise propagate parser
failures. There is no index run, per-source result, retry state, parsing-failure issue, worker timeout,
or continuation across multiple files.

The local browser limits an uploaded PDF to 100 pages only after opening it for `page_count()`
([`pdf_mcp/web_app.py:234`](pdf_mcp/web_app.py#L234)). DOCX validation checks only the ZIP prefix before
`python-docx` opens it ([`pdf_mcp/web_app.py:118`](pdf_mcp/web_app.py#L118)). This is reasonable for a
user-selected local beta, but not sufficient for unattended scans of large or hostile source trees.

### 6. Configuration and no-egress policy are fragmented

**Severity: High.**

File policy, cloud settings, and Stripe settings use unrelated environment variables and code paths.
There is no `SMART_LAB_INDEX_NO_EGRESS` switch, no module declaration of network/file/credential needs,
and no registry policy that can block an incompatible module. The hosted client is explicit opt-in and
HTTPS-restricted ([`pdf_mcp/cloud_client.py:35`](pdf_mcp/cloud_client.py#L35)), which is a useful local
precedent, but it is not a platform-level fail-closed mechanism.

### 7. The UI is coupled to one capability

**Severity: Medium.**

Both backend routes and frontend navigation assume a single document conversion task. The format list
is duplicated between backend constants and static controls
([`pdf_mcp/web_app.py:30`](pdf_mcp/web_app.py#L30),
[`pdf_mcp/web_ui/index.html:59`](pdf_mcp/web_ui/index.html#L59)). Future entity, source, issue, review,
and module views cannot be added cleanly without a small capability/view registry.

### 8. Packaging makes built-in parser dependencies inseparable

**Severity: Medium.**

All installations receive PDF, DOCX, and OpenPyXL dependencies
([`pyproject.toml:14`](pyproject.toml#L14)). This is acceptable for the first built-in module bundle, but
the Core package must not import these libraries. There is no lockfile, and dependency versions have no
upper bounds.

### 9. Tests protect behavior but not boundaries

**Severity: Medium.**

The 103 passing tests provide a strong characterization base. They do not test a parser interface,
connector replacement, module enable/disable, dependency validation, module health, no-egress rejection,
index-run persistence, per-file failure isolation, or Core operation with optional modules absent. CI
runs tests and profile gates only ([`.github/workflows/ci.yml:32`](.github/workflows/ci.yml#L32)).

Some tests reinforce closed-world assumptions, notably the exact two-profile assertion in
[`tests/test_profiles.py:26`](tests/test_profiles.py#L26). Static analysis is also not gated; the audit's
Ruff run found 30 findings.

## Minimal target boundaries

The smallest architecture that creates real modularity is:

```text
smart_lab_index/
  core/
    models          Entity, Alias, Source, Document, Assertion, Provenance,
                    Issue, IndexRun, ReviewDecision, AuditEvent
    contracts       Connector, Parser, Extractor, Resolver, IssueRule, Search
    modules         Manifest, registry, capability lookup, health, config
    services        indexing orchestration, assertion service, review service
    repositories    stable storage interfaces
    events          synchronous in-process dispatcher
    policy          file access and no-egress enforcement

  modules/
    connector_filesystem
    parser_pdf
    parser_docx
    parser_xlsx
    parser_csv
    parser_txt
    extractor_structured
    resolver_identifier
    resolver_alias
    resolver_normalized_name
    relationship_structured
    issue_basic
    search_lexical
    export_tabular
    interface_mcp
    domain_general_lab

  web/
    local host and capability-aware views
```

This is an architectural intent, not a requirement to create all folders immediately. A small number of
typed protocols and dataclasses plus a registry is sufficient for the first iteration.

## Required contracts before refactoring

### Module manifest

At minimum: stable module ID, name, version, type, description, Core compatibility, dependencies,
capabilities, configuration schema, and declared network/file/credential needs. Health should distinguish
enabled, disabled, healthy, degraded, misconfigured, unavailable, and error states.

### Connector contract

The connector must emit normalized `SourceRecord` values with source/external IDs, display name,
path/reference, content type, modified time, size, checksum or change token, metadata, permission
metadata, and a content reference. It must return per-record failures instead of aborting a discovery
run.

### Parser contract

A parser must consume a Core-owned content reference and return one normalized `DocumentContent` shape:
text blocks, tables, headings, pages/sheets, cells, metadata, warnings, and provenance references. Parser
outputs must include module ID/version. Parsers must not create entities or write source files.

### Extraction and assertion contracts

Extraction modules should emit candidates with evidence. Relationship modules should propose assertions.
Only a Core assertion service should persist assertions, enforce controlled predicates/statuses, attach
provenance, and emit events. No module should directly overwrite a resolved current value.

### Registry contract

The registry should be constructed explicitly at startup from built-in manifests. It should validate
IDs, compatibility, dependencies, duplicate capabilities, config, no-egress policy, and health. Dynamic
package installation and a marketplace are not needed.

## Reuse plan by risk

### Reuse with a thin adapter first

- `extractor.extract_text()` and `extractor.extract_tables()` as the initial `parser.pdf` implementation.
- `docx_extractor.extract_docx_text()` and `extract_docx_tables()` as `parser.docx`.
- `output_safety.spreadsheet_safe()` inside an export module.
- `profiles.validate_profile()`, `normalize_header()`, and `profile_sha256()` as configuration utilities
  for structured extraction.
- loopback server/session/CSP patterns for the local UI host.
- existing parser, profile, evidence, and web tests as characterization tests.

Adapters should translate existing dictionaries into the normalized contract without initially changing
legacy command output.

### Extract only after contracts exist

- `_document()` hashing from `verified.py` into a source/content service;
- `_header_match()`, `_convert()`, and `_extract_records()` into `extractor.structured`;
- duplicate-key and table-quality findings into issue modules;
- engine/profile fingerprinting into index-run provenance;
- XLSX/CSV/JSON writers into export capabilities; and
- MCP tool declarations into capability-driven registration.

### Do not treat as Core

- extraction profiles and their record schemas;
- parser-specific table dictionaries;
- FastMCP objects;
- HTTPX clients;
- OpenPyXL workbook objects;
- web handler classes;
- Stripe/offer metadata;
- fictional Northstar Water terminology; or
- the current `accepted/needs_review/rejected` document-profile decision as the universal assertion
  status model.

## Safest migration sequence

1. **Freeze legacy behavior with characterization tests.** Preserve all 103 passing tests and add
   contract-focused tests without changing public commands.
2. **Introduce typed neutral contracts and a built-in module registry.** Register metadata only at
   first; do not move algorithms yet.
3. **Move file access policy out of the PDF parser.** Provide Core-owned read-only content access and
   streaming hashing. Keep a compatibility `_check_path()` wrapper temporarily.
4. **Define `DocumentContent` and adapt PDF first.** Route one new internal ingestion path through the
   parser registry while old extraction APIs continue to delegate or remain unchanged.
5. **Adapt DOCX, then implement XLSX/CSV/TXT parsers.** Remove shared private imports from the PDF
   module only after parity tests pass.
6. **Add SQLite-backed Core repositories and migrations.** Store sources, documents, index runs,
   entities, aliases, assertions, provenance, issues, review decisions, and audit events.
7. **Implement `connector.filesystem`.** Make discovery recursive, read-only, incremental, permission-
   aware where available, and isolated per path. Persist changed, unchanged, deleted, and failed counts.
8. **Extract structured mapping and issue rules from `verified.py`.** Modules emit candidates/assertions;
   Core persists them non-destructively.
9. **Add a synchronous event dispatcher and capability-aware UI registry.** Keep both intentionally small.
10. **Add explicit no-egress enforcement before any inference module.** Only then consider optional local
    AI and embeddings.

This sequence keeps existing user value available and avoids a big-bang rewrite.

## First-iteration acceptance check against the repository

| Required outcome | Current state | Work needed |
| --- | --- | --- |
| Existing useful functionality remains working | Yes, 103 tests pass | Preserve via compatibility adapters. |
| Core independent of filesystem implementation | No Core; path policy lives in PDF parser | Introduce content/file policy contract. |
| Core independent of PDF implementation | No Core; many modules depend on PDF private helpers | Remove accidental infrastructure ownership from `extractor.py`. |
| At least one replaceable connector | No connector exists | Implement connector contract and filesystem module. |
| At least one parser through an interface | No parser interface exists | Adapt PDF first. |
| Modules report ID/version/enablement/health | Not implemented | Add minimal manifest and registry. |
| Entities/assertions have provenance | Not implemented | Add Core models/repositories and assertion service. |
| One module failure does not kill a run | No batch/index run exists | Add per-source outcomes and parsing-failure issue. |
| No organization-specific production data | Satisfied | Retain synthetic-data controls. |

## Architectural risks to control

1. **Schema lock-in:** do not shape Core tables around current extraction-result JSON.
2. **Compatibility breakage:** retain existing console commands and MCP behavior while adapters mature.
3. **Plugin overengineering:** built-in modules and explicit startup registration are enough for the MVP.
4. **Hidden imports:** enforce `modules -> core contracts/services`; prohibit module imports of another
   module's internals.
5. **Unattended parser resource use:** add time, size, archive, concurrency, and per-file failure controls
   before recursive scanning is considered production-safe.
6. **False provenance confidence:** normalized cells must keep exact source references and parser/module
   versions; a clean parse is not confirmation of a fact.
7. **No-egress bypass:** enforce policy centrally at registration and capability acquisition, not only by
   convention inside each network module.
8. **Core growth:** domain terminology, parser heuristics, vendor APIs, UI labels, and AI prompts belong in
   modules/configuration, not Core.

## Decision

The existing document processor should be retained, but only as a set of ingestion and support
capabilities. Its tested deterministic extraction and provenance mechanics are worth reusing. Its current
orchestrators, dictionaries, direct imports, and converter UI are not a sufficient foundation for the
LabOverlay Core.

The next implementation step should be narrowly scoped: define the neutral Core contracts and minimal
built-in module registry, then place the existing PDF extractor behind the first parser adapter while
keeping every legacy command and test operational.

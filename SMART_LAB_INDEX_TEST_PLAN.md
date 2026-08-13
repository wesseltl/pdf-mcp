# LabOverlay First-Iteration Test Plan

## Purpose

This plan defines the focused synthetic test strategy for the first modular LabOverlay
foundation. It covers the module registry, no-egress enforcement, filesystem discovery, parser
contracts, assertion-based knowledge, SQLite durability, failure isolation, and preservation of the
existing document-processing commands.

The first iteration is successful when these tests demonstrate real internal module boundaries. A
test that only checks class names or directory layout is insufficient.

## Repository Test Baseline

The repository currently has these relevant characteristics:

- Python 3.10+ and standard-library `unittest` are the established test stack.
- CI installs the editable package with `python -m pip install -e ".[test]"` and runs
  `python -m unittest discover -s tests` on Python 3.10, 3.11, and 3.12.
- Existing tests generate PDF and DOCX inputs at runtime with ReportLab and python-docx. XLSX
  inspection already uses openpyxl.
- Existing reusable production behavior is concentrated in `pdf_mcp/extractor.py`,
  `pdf_mcp/docx_extractor.py`, and `pdf_mcp/exporter.py`.
- Existing command coverage includes table export, profile extraction/evaluation, local MCP
  wrappers, the local browser app, the optional hosted bridge, and version/launch metadata.
- There is currently no SQLite persistence layer, module registry, filesystem index connector, or
  common PDF/DOCX/XLSX/CSV/TXT `DocumentContent` contract.

The audit run in this shell was not a valid full-suite baseline because the system Python lacks
`pdfplumber`, `python-docx`, and `openpyxl`. Twenty-five dependency-free tests passed and eight test
modules failed during import. The authoritative baseline must be captured after installing
`.[test]`, using the same command as CI.

## Test Boundaries

Use the existing `unittest` style. Add future LabOverlay tests as focused files such as:

```text
tests/
    sli_fixtures.py
    test_sli_module_registry.py
    test_sli_no_egress.py
    test_sli_filesystem_connector.py
    test_sli_parsers.py
    test_sli_knowledge.py
    test_sli_persistence.py
    test_sli_end_to_end.py
    test_sli_command_regressions.py
```

All generated files, databases, and connector state must live in `TemporaryDirectory` instances.
The SQLite database must be outside the directory scanned by the filesystem connector, otherwise the
connector can index its own changing database.

Test public Core interfaces wherever possible. Direct SQL is appropriate only for migration,
foreign-key, and transaction invariants. Do not make tests depend on private table layouts for
ordinary repository behavior.

No test may require internet access, a cloud account, a model download, a running inference server,
wall-clock sleeps, or real laboratory data.

## Synthetic Vocabulary

All new LabOverlay fixture entity values are limited to:

```python
LAB_ALPHA = "Lab Alpha"
SITE_NORTH = "Site North"
ROOM_A_101 = "Room A-101"
ROOM_A_102 = "Room A-102"
FREEZER_001 = "Freezer-001"
ALEX_EXAMPLE = "Alex Example"
```

Headers, predicates, file names, module IDs, and entity type names are schema vocabulary rather than
fixture entities. Existing document-processor regression fixtures remain unchanged, but they must
not be reused as LabOverlay domain evidence.

## Generated Fixture Factories

`tests/sli_fixtures.py` should generate inputs at runtime. Generated office documents avoid opaque
binary fixtures and make every assertion reviewable.

### 1. Connector Scan Tree

```text
sample_lab/
    locations.txt
    equipment.csv
    responsibilities.csv
    SOPs/
        SOP_freezers.docx
    inaccessible.txt
```

Contents:

| File | Synthetic content |
| --- | --- |
| `locations.txt` | `Lab Alpha`, `Site North`, `Room A-101`, and `Room A-102`, one line each |
| `equipment.csv` | Header `asset,location`; row `Freezer-001,Room A-101` |
| `responsibilities.csv` | Header `person,asset`; row `Alex Example,Freezer-001` |
| `SOPs/SOP_freezers.docx` | Paragraph stating `Freezer-001 located_in Room A-102` |
| `inaccessible.txt` | `Lab Alpha`; the file exists, but the test access adapter raises `PermissionError` for it |

Do not use `chmod` to create the inaccessible case. Permission-bit behavior differs for root,
Windows, and CI. Inject or patch the narrow file-open/stat boundary for exactly
`inaccessible.txt`, and assert that all other files continue.

### 2. Parser Corpus

Generate one valid source per required parser:

| Parser | File | Minimum structure and expected provenance |
| --- | --- | --- |
| `parser.pdf` | `locations.pdf` | A text block and two-row location table; page number and bounding boxes where the underlying parser supplies them |
| `parser.docx` | `SOP_freezers.docx` | One paragraph with the Room A-102 assertion and one table; paragraph/table/row/column references |
| `parser.xlsx` | `equipment.xlsx` | Sheet `Equipment`, header row, and `Freezer-001` / `Room A-101` row; sheet name and cell/row references |
| `parser.csv` | `responsibilities.csv` | `Alex Example` / `Freezer-001`; row and column references |
| `parser.txt` | `locations.txt` | The four location/organization lines; one-based line references |

Also generate `broken.pdf` with an invalid PDF byte sequence. Place a valid TXT source after it in
the deterministic work list so the test proves that one parser failure does not stop subsequent
documents.

### 3. Conflict Corpus

```text
sample_lab/
    locations.xlsx
    equipment.xlsx
    responsibilities.xlsx
    SOPs/
        SOP_freezers.docx
```

Rows and statements:

- `locations.xlsx`: `Lab Alpha` is an ORGANIZATION; `Site North` is a LOCATION associated with
  `Lab Alpha`; `Room A-101` and `Room A-102` have `Site North` as parent.
- `equipment.xlsx`: `Freezer-001` is an ASSET and is `located_in` `Room A-101`.
- `responsibilities.xlsx`: `Alex Example` is a PERSON and is `responsible_for` `Freezer-001`.
- `SOPs/SOP_freezers.docx`: `Freezer-001` is `located_in` `Room A-102`.

Expected canonical entities are `Lab Alpha` as ORGANIZATION, `Site North`, `Room A-101`, and
`Room A-102` as LOCATION, `Freezer-001` as ASSET, and `Alex Example` as PERSON. Subtypes may come
from `domain.general_lab`; they must not change the Core canonical types.

Expected conflict behavior:

- The two `located_in` assertions have distinct assertion IDs and share the same resolved
  `Freezer-001` subject.
- Neither assertion overwrites or deletes the other.
- Spreadsheet provenance identifies `equipment.xlsx`, sheet `Equipment`, and row 2 or its equivalent
  structural reference.
- DOCX provenance identifies `SOPs/SOP_freezers.docx` and the exact paragraph index.
- The conflict rule creates one open `CONFLICTING_LOCATION` issue referencing both assertions.
- With no source-authority rule configured, the current location is unresolved/conflicted rather
  than silently selected.
- Re-indexing unchanged inputs creates neither duplicate assertions nor duplicate open issues.

## Deterministic Test Doubles

Use small in-test modules implementing the approved module contract. They must not introduce a
second plugin design.

- `RecordingModule`: records initialize/start/health/stop calls and exposes a manifest.
- `UnavailableModule`: returns `UNAVAILABLE` without raising.
- `FailingStartModule`: raises during `start`; another optional module must still become healthy.
- `FailingParser`: raises a typed parse error only for `broken.pdf`.
- `ExternalNetworkModule`: declares external network access and raises if lifecycle code is called;
  under no-egress its call log must stay empty.
- `FixedClock`: returns explicit UTC instants for index-run and audit assertions.
- `FixedIdFactory`: supplies stable IDs only where exact IDs are material to a test. Production IDs
  do not need to be predictable.

Filesystem tests should use a narrow injectable access boundary or mocks around stat/open/scandir.
They must use real temporary files for normal scanning and hashing; a fully mocked filesystem would
not test recursive discovery or checksums.

## Contract Assertions

### Module Registry

The tests should require the registry to expose, through one stable Core interface:

- module ID, name, type, version, compatibility, dependencies, capabilities, and security metadata;
- installed versus enabled state;
- health state and a bounded human-readable reason;
- validated configuration without leaking secrets;
- deterministic dependency ordering;
- lifecycle isolation for optional module failures.

Disabling a module must prevent initialization, startup, event subscription, and capability
selection. Missing, disabled, cyclic, or version-incompatible dependencies must be reported before
the dependent module starts. Duplicate module IDs and invalid manifests must fail explicitly.

Health tests must distinguish `HEALTHY`, `DISABLED`, `DEGRADED`, `MISCONFIGURED`, `UNAVAILABLE`, and
`ERROR`. A module exception must be converted into registry health and an audit-safe error, not left
as an unhandled application exception.

### No-Egress

With `SMART_LAB_INDEX_NO_EGRESS=true`:

- modules declaring external network, cloud inference, external embeddings, telemetry, analytics,
  automatic downloads, or unknown/omitted egress metadata are rejected before lifecycle methods run;
- local modules declaring no network access remain usable;
- a blocked preferred provider is not silently replaced by any external provider;
- the registry exposes a blocked/misconfigured reason and records an audit event without secrets;
- the existing optional hosted bridge must fail before constructing an HTTP client when invoked in
  this mode.

The test should patch the HTTP/client boundary with a mock that fails if called. This proves fail
closed behavior without making a network request. Test both the typed configuration path and the
literal environment variable. Invalid boolean values must fail configuration validation rather than
defaulting no-egress off.

### Filesystem Connector

The connector contract should return normalized `SourceRecord` changes and per-path failures, not
parser-specific objects. Required assertions:

- recursive, read-only discovery with normalized relative path provenance;
- source ID/external ID stability across runs;
- size, modification timestamp, media type, and SHA-256 checksum capture;
- first run reports discovered/new records;
- an immediate second run reports all records unchanged and schedules no parser work;
- changed contents report exactly one changed record;
- same-size content changed while restoring the original modification time is still detected by its
  checksum;
- deletion emits exactly one deletion/tombstone while preserving historical source and provenance;
- `PermissionError` on one file produces one bounded failure and the remaining records continue;
- connector input bytes and timestamps are identical before and after a completed index run.

Do not assert discovery order unless the contract deliberately specifies sorting. Compare records by
relative path. Ignore the SQLite database, output directory, and connector state directory by
placing them outside the source root, not through fixture-specific product rules.

### Parser Normalization and Provenance

Every parser must return the same top-level `DocumentContent` shape, with format-specific structure
inside typed blocks/tables:

- source record/document identity;
- media/content type;
- text blocks;
- tables with rows/cells;
- document metadata;
- warnings;
- parser module ID and version;
- structural provenance attached to every extracted block, table, and cell where applicable.

The common contract must be sufficient for downstream extractors without importing parser internals.
Tests should use one shared conformance assertion against PDF, DOCX, XLSX, CSV, and TXT results, then
make format-specific provenance assertions. Absolute temporary paths must not become durable entity
identity.

Parser selection must occur through a capability/registry interface. Replace `parser.txt` with a
recording parser in one orchestration test and prove that no Core orchestration code changes are
needed. A missing parser creates a bounded unsupported-content issue; a corrupt document creates a
parsing-failure issue; neither aborts other documents in the index run.

### Entity, Assertion, and Issue Behavior

Run the conflict corpus through deterministic modules only. Assert:

- canonical entity types stay generic;
- exact identifier, alias, then normalized-name resolvers execute in configured order;
- references to `Freezer-001` resolve to one ASSET without losing resolver evidence;
- assertions carry subject, predicate, object/literal, confidence, status, extraction method,
  extraction/module version, source, structural provenance, and timestamps;
- observed assertions remain separate from any resolved current value;
- conflicting location assertions create one traceable issue;
- `Alex Example responsible_for Freezer-001` remains independent of the location conflict;
- no assertion is generated without source evidence;
- repeating the same run is idempotent.

The first deterministic MVP must pass this test with inference and embedding capabilities disabled.

### SQLite Persistence

Use a file-backed temporary SQLite database and the Core repository/service API. Required assertions:

- a fresh database initializes to the expected schema version and enables foreign keys;
- migrations are repeatable and do not erase existing data;
- source records, documents, entities, aliases, assertions, provenance, issues, index runs, review
  decisions, audit events, and persisted module configuration/state survive close and reopen;
- assertion-to-source and issue-to-assertion links survive restart;
- uniqueness/idempotency constraints prevent duplicate source records and duplicate observations from
  an unchanged re-index;
- deleting a source from the connector marks its current source state without deleting historical
  assertions or provenance;
- a forced failure in the middle of a Core write transaction rolls back the complete unit of work;
- module code receives repository/service interfaces rather than a raw cross-module SQLite handle.

Do not lock tests to generated timestamp strings or row ordering. Query through repositories and use
the fixed clock where an exact timestamp matters.

### Existing Command Regressions

Keep the complete existing suite as a release gate. In addition, preserve these behaviors during the
module extraction:

- `export-document-tables` still converts supported PDF/DOCX tables and retains review warnings and
  spreadsheet formula protection.
- `extract-document-with-profile` and `evaluate-document-profile` retain their exit-code contracts.
- `pdf-agent-mcp` still exposes the existing local extraction/profile tools, now delegating through
  compatible parser capabilities where practical.
- `pdf-mcp-app` remains loopback-only, session-protected, and able to convert and download a result.
- `pdf-agent-cloud-mcp` remains explicit opt-in, redacts secrets, and is blocked by LabOverlay
  no-egress mode before HTTP setup.
- package/server metadata versions remain consistent.

Run command smoke tests in subprocesses only where process behavior, exit status, or entry-point
packaging matters. Continue direct `main()` calls for narrow argument/result tests to keep the suite
fast.

## Prioritized Acceptance Matrix

Priority meanings:

- **P0**: merge blocking for the first modular foundation.
- **P1**: required before calling the first iteration complete.
- **P2**: hardening after the foundation contract is stable.

| Priority | ID | Acceptance test | Required result |
| --- | --- | --- | --- |
| P0 | REG-01 | Register and list valid built-in modules | IDs, versions, types, capabilities, enabled state, and security metadata are visible |
| P0 | REG-02 | Disable `parser.pdf` | No lifecycle call, hook, or capability contribution occurs; health is `DISABLED` |
| P0 | REG-03 | Disabled/missing dependency | Dependent module is `MISCONFIGURED` and never starts |
| P0 | REG-04 | Optional module start failure | Failed module is `ERROR`; independent module reaches `HEALTHY`; startup report contains both |
| P0 | EGR-01 | Enable no-egress with an external-network module installed | Module is blocked before initialize/start and an audit-safe reason is exposed |
| P0 | EGR-02 | Enable no-egress with local connector/parsers | Local capabilities remain available and no network mock is called |
| P0 | FS-01 | First recursive connector scan | Every accessible file produces one stable, checksummed normalized source record |
| P0 | FS-02 | Repeat unchanged scan | All records are unchanged, no duplicate rows are stored, and no parser is scheduled |
| P0 | FS-03 | Modify one file, then delete one file | Exactly one change and one deletion are reported across the respective runs |
| P0 | FS-04 | One injected `PermissionError` | One bounded failure is recorded; all accessible files continue; source files remain unchanged |
| P0 | PAR-01 | Parser contract conformance for PDF/DOCX/XLSX/CSV/TXT | Every result matches `DocumentContent` and records parser ID/version |
| P0 | PAR-02 | Format-specific provenance | PDF page, DOCX structural index, XLSX sheet/cell, CSV row/column, and TXT line survive normalization |
| P0 | PAR-03 | Corrupt PDF followed by valid TXT | Parsing failure issue is stored and valid TXT still parses in the same run |
| P0 | KNW-01 | Index the conflict corpus without AI | Six canonical entities and evidence-backed assertions are produced through configured modules |
| P0 | KNW-02 | Detect conflicting location | Both location assertions remain and one `CONFLICTING_LOCATION` issue references both |
| P0 | DB-01 | Close and reopen SQLite | Core records and their provenance links are unchanged after restart |
| P0 | DB-02 | Re-index unchanged conflict corpus | Entity, assertion, source, and open-issue counts do not grow |
| P0 | CMD-01 | Run existing `unittest` suite after refactor | All pre-existing tests pass on Python 3.10, 3.11, and 3.12 |
| P1 | REG-05 | Duplicate ID, invalid manifest, dependency cycle, and version mismatch | Each fails explicitly before startup with no partial registration |
| P1 | REG-06 | Lifecycle ordering and stop | Dependencies start first; enabled modules stop once in reverse order |
| P1 | REG-07 | Health refresh | `DEGRADED`, `UNAVAILABLE`, and recovery to `HEALTHY` are reported without reinstalling |
| P1 | EGR-03 | Missing egress declaration under no-egress | Module is rejected fail closed |
| P1 | EGR-04 | Invoke hosted bridge under no-egress | Typed error/exit occurs before an HTTP client is constructed |
| P1 | FS-05 | Same-size content mutation with restored mtime | Checksum detects the changed file |
| P1 | FS-06 | Snapshot source tree before/after indexing | File bytes, mtimes, and directory entries are unchanged |
| P1 | PAR-04 | Replace parser implementation through registry | Orchestrator consumes the replacement through the same contract |
| P1 | PAR-05 | Unsupported extension or disabled parser | One bounded issue is recorded; run continues |
| P1 | KNW-03 | Resolver ordering and evidence | Exact ID precedes alias and normalized name; evidence from each attempted stage is retained |
| P1 | KNW-04 | Repeat issue detection | Existing open conflict issue is reused, not duplicated |
| P1 | DB-03 | Forced repository failure inside a transaction | No partial source/document/assertion graph is committed |
| P1 | DB-04 | Connector deletion followed by restart | Source is marked absent while historical assertion provenance remains queryable |
| P1 | RUN-01 | Inspect completed/degraded index run | Counts, enabled module IDs/versions, failures, start/end, and status are reproducible |
| P1 | CMD-02 | Entry-point smoke tests | Export, profile, MCP import/delegation, browser conversion, and version behavior remain compatible |
| P2 | REG-08 | Concurrent health reads and configuration update | Registry state stays internally consistent |
| P2 | FS-07 | Symlink loop and source-root escape | Scan terminates and does not escape configured read scope |
| P2 | FS-08 | Large synthetic tree | Incremental scan remains bounded and unchanged files are not reparsed |
| P2 | DB-05 | Interrupted migration recovery | Database reopens at either old or new complete schema, never a partial schema |
| P2 | RUN-02 | Re-index after parser/module version change | Only affected generations are scheduled and prior generation provenance remains traceable |

## Minimum Merge-Blocking Slice

The smallest acceptable implementation slice is the 18 P0 rows above. To keep feedback fast, those
rows should be represented by approximately 12 focused test methods, combining only closely related
assertions:

1. Registry lists manifests and a disabled module contributes nothing.
2. Missing/disabled dependency blocks startup.
3. One optional module fails while an independent module remains healthy.
4. No-egress blocks an external module before lifecycle code and permits local modules.
5. Filesystem first scan and unchanged second scan are incremental and idempotent.
6. Filesystem content change and deletion are detected.
7. One inaccessible file is isolated and source files remain read-only.
8. All five parsers satisfy the shared normalized contract and format provenance checks.
9. A corrupt PDF creates a failure issue while a later TXT document succeeds.
10. The conflict corpus preserves both location assertions and creates one traceable issue without AI.
11. SQLite close/reopen and unchanged re-index preserve links and counts.
12. The complete pre-existing test suite passes unchanged.

This slice is the foundation gate. P1 remains required before the first iteration is declared
complete, but P0 should run on every branch while interfaces are being established.

## Execution Commands

From the repository root:

```bash
python -m pip install -e ".[test]"
python -m unittest discover -s tests -p "test_smart_lab_*.py" -v
python -m unittest discover -s tests -v
evaluate-document-profile evaluations/sample-invoice.json
evaluate-document-profile evaluations/simulated-customer/development.json
evaluate-document-profile evaluations/simulated-customer/holdout.json
```

The LabOverlay tests must run successfully with network access unavailable. CI should execute the
full suite on Python 3.10, 3.11, and 3.12, preserving the current matrix.

## First-Iteration Exit Criteria

- Every P0 and P1 row passes.
- Existing command and profile gates pass without fixture rewrites that weaken their assertions.
- The conflict demonstration succeeds with inference and embeddings absent or disabled.
- No test observes an outbound connection.
- A connector or parser can be replaced by a test double through its approved interface.
- A parser/module failure produces bounded health/issues and does not terminate unrelated work.
- SQLite restart retains original assertions and structural provenance.
- New fixture entity values contain only the approved synthetic vocabulary.

## Deliberate Deferrals

Do not add first-iteration tests that force implementation of local AI, embeddings, semantic search,
vendor connectors, source permission enforcement, a plugin marketplace, multi-process workers, or a
distributed broker. Preserve interface space for those capabilities, but test only the modular
foundation being built now.

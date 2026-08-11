# Smart Lab Index Security / No-Egress Baseline Review

## Audit metadata

- Repository: `/root/pdf-mcp`
- Reviewed commit: `fb9ae62` (`agent/smart-lab-index-foundation`, also `main` at review start)
- Review date: 2026-08-11
- Review type: static first-party source, configuration, test, packaging, and workflow audit
- Application code changes: none

## Foundation implementation update

The remainder of this document preserves the pre-implementation baseline at commit `fb9ae62`.
The current foundation branch has since implemented the first-party application-policy controls and
addressed the critical connector/provenance findings identified during integration:

- Core now strictly parses `SMART_LAB_INDEX_NO_EGRESS`, and the built-in module registry blocks
  configured-endpoint/internet modules before start while allowing explicit loopback modules.
- Every current Smart Lab Index built-in exposes versioned capabilities plus network, file,
  credential, dependency, configuration, lifecycle, health, telemetry, automatic-download,
  subprocess, and source-write metadata.
- The retained hosted extraction bridge refuses in no-egress mode before cloud configuration is read
  or an HTTP client is constructed. Tests cover upload and usage paths.
- The filesystem connector accepts regular files only, rejects symlinks/root escapes, uses no-follow
  opens where supported, verifies the opened identity, parses checksum-validated immutable snapshots,
  and isolates inaccessible records. Core state is rejected inside a source root and database
  hardlinks are rejected.
- Core state directories and SQLite files are created with private owner-only modes. Module/event
  failures use bounded generic details, and configuration snapshots redact secret-like fields.
- Source generations and transactional extractor processing preserve the last successful assertions
  when a changed source fails. Modules receive narrow read-only repository facades.
- Smart Lab Index `0.2.0` adds a loopback-only operator GUI with a random browser-session token,
  same-origin checks on mutations, no-store responses, a restrictive CSP, bundled assets, bounded
  request bodies, and no external links or runtime asset requests. SQLite connections remain local
  to the request or background index thread.
- Parsers receive read-only streams and failures are isolated per record. Current parser hardening
  does not yet provide subprocess, timeout, memory, or expanded-archive limits.

Accordingly, `NE-001` through `NE-004` are remediated for the explicitly registered Smart Lab Index
runtime path, and the connector now enforces the first source-root boundary. The retained legacy
browser/export commands remain compatibility surfaces with their separately documented behavior.
The remaining findings, especially hostile-parser resource isolation, dependency locking/offline
distribution, complete log redaction, packaged-artifact testing, at-rest encryption, and OS-level
network denial, remain open. Application policy is not a sandbox for malicious in-process plugins.

Post-implementation validation on 2026-08-11 passed all 151 repository tests, including 46 focused
Smart Lab tests and five real-HTTP GUI tests. A complete built-in no-egress indexing run was executed
with socket connection calls intercepted and made zero attempts. This supports controlled synthetic
evaluation; it is not a claim that the process contains malicious code or is ready for hostile
documents and confidential shared laboratory roots.

This review covers every current executable path declared in `pyproject.toml:31-37`, their shared
runtime components, the static website, operational scripts, build/release automation, and every
module category proposed for Smart Lab Index. It distinguishes observed repository facts from
requirements for the planned product.

This is not a penetration test of an operating-system image or the unavailable hosted backend. The
direct dependencies are version ranges rather than a locked, vendored set (`pyproject.toml:14-21`),
so claims about transitive-package behavior cannot be proved from this repository alone. The hosted
service implementation called by `pdf_mcp/cloud_client.py` is also not present and cannot be audited.

## Executive verdict

**Current fact:** The local parser, exporter, profile, evaluator, MCP, and browser-app first-party
code contains no outbound HTTP client, telemetry SDK, analytics client, model call, embedding call,
or runtime asset/model downloader. PDF/DOCX parsing and XLSX export are deterministic and local. The
local browser UI serves bundled assets and its automatic `fetch` calls are same-origin loopback calls.

**Current fact:** Other paths in the same repository intentionally make external requests:

- `pdf-agent-cloud-mcp` uploads selected document bytes and sends an API key to a configured service.
- The public website automatically fetches offer metadata from GitHub.
- The live Stripe administration script creates remote Stripe objects.
- CI, Pages, and release workflows download packages/actions and publish artifacts.

**Current fact:** `SMART_LAB_INDEX_NO_EGRESS` is not referenced anywhere in the repository. Setting it
to `true` currently changes nothing. In particular, it does not stop the cloud MCP bridge from
reading and uploading a document.

**Verdict:** The repository has a useful local-first starting point, but it does **not** currently
meet the fail-closed Smart Lab Index no-egress requirement. No-egress must not be advertised as an
enforced product mode until blockers `NE-001` and `NE-002` and all first-iteration requirements below
are implemented and tested.

## Evidence labels

The following labels are used throughout:

- **CURRENT FACT**: directly evidenced by the reviewed repository.
- **ASSURANCE GAP**: behavior is not implemented, not testable from this repository, or delegated to
  an unpinned dependency or external system.
- **REQUIREMENT**: required change for the first Smart Lab Index foundation; it is not current
  behavior.
- **FUTURE RECOMMENDATION**: useful hardening after the first iteration, not an MVP prerequisite.

## Blocking findings

| ID | Severity | Current fact / assurance gap | Required disposition |
|---|---|---|---|
| `NE-001` | Critical | `SMART_LAB_INDEX_NO_EGRESS` has no implementation. `pdf_mcp/cloud_client.py:34-58`, `87-104`, and `146-157` construct external clients without consulting a global policy. | Parse policy once at startup, reject invalid values, block incompatible modules before initialization, and enforce it again at every outbound call boundary. A blocked call must occur before file open, DNS, socket creation, or credential access. |
| `NE-002` | Critical | There is no Core security policy, module manifest security declaration, module registry enforcement, or centralized network boundary. Future modules could make hidden network calls or auto-download models. | Make resource declarations mandatory and schema-validated. Registry enable/start must fail closed for incompatible modules. Route built-in network and inference access through policy-enforcing Core interfaces. |
| `NE-003` | High | The package exposes the explicit cloud bridge as a normal console entry point (`pyproject.toml:34`). It uploads the complete selected file as multipart content (`pdf_mcp/cloud_client.py:87-104`). Existing tests prove that behavior (`tests/test_cloud_client.py:90-100`). | Mark the module `network=external`, `no_egress_compatible=false`; in no-egress mode report `BLOCKED_BY_POLICY` and refuse before reading a path. Never fall back to it from a local module. |
| `NE-004` | High | Agent-facing local MCP tools can read supported files and write exports anywhere allowed by the process unless the optional `PDF_MCP_ALLOWED_DIR` is set (`pdf_mcp/extractor.py:13-36`, `pdf_mcp/server.py:27-149`). | Require explicit source roots and separate state/export/temp roots in Smart Lab Index. Use read-only connector handles and Core-owned write repositories. Optional unrestricted host access is not an acceptable indexing default. |
| `NE-005` | High | Local CLI/MCP parsers have no common byte/page/expanded-archive/CPU/memory/time limits or parser process isolation. The browser path limits upload bytes, PDF pages, and output bytes (`pdf_mcp/web_app.py:23-29`, `227-256`), but DOCX is only checked for a ZIP prefix (`pdf_mcp/web_app.py:118-123`). | Add bounded parser execution and per-record failure isolation before recursively indexing untrusted trees. A malformed or compressed-bomb document must create a parser-failure issue without stopping the run. |
| `NE-006` | High | Offline installation/build reproducibility is absent. Runtime/build dependencies use open-ended minimum versions, CI installs from package indexes, and GitHub Actions use mutable major-version tags (`pyproject.toml:14-21`, `.github/workflows/ci.yml:23-33`, `.github/workflows/publish.yml:18-28`). | Produce a pinned, hash-verified offline bundle or wheelhouse/SBOM for no-egress deployments. Pin release actions by commit digest and verify downloaded publisher artifacts. Runtime must never invoke package installation. |
| `NE-007` | Medium | Logging has no shared redaction policy. Browser debug request logs can include the filename carried in the conversion query, exception traces are logged, and the manual inspector prints paths and extracted rows (`pdf_mcp/web_app.py:166-167`, `211-212`, `221-223`; `tests/manual/inspect_document.py:19-43`). | Define structured redaction rules. Never log source text, table cells, secrets, query-string filenames, or full customer paths by default. Test with canary content and credentials. |
| `NE-008` | Medium | Browser temporary source copies are plaintext. They are context-managed, but an uncatchable termination can leave them behind. If `PDF_MCP_ALLOWED_DIR` is set, the app deliberately places its temporary directory under that source root (`pdf_mcp/web_app.py:232-237`). | Use a dedicated private Core temp root, never a source root; set restrictive permissions; clean on success/failure; and scavenge stale application-owned temp directories on startup. |
| `NE-009` | Medium | The local UI has bundled assets and a restrictive CSP, but displays user-clickable GitHub links (`pdf_mcp/web_ui/index.html:17`, `138-142`). Profile output embeds a remote GitHub `$schema` URL (`pdf_mcp/verified.py:541-552`). The application does not fetch that schema, but downstream tools may. | In no-egress mode hide or clearly block external UI actions and emit a local/URN schema identifier. Do not include remote fonts, scripts, styles, images, schemas, or update checks. |
| `NE-010` | Medium | Hosted retention, bounded logging, parser subprocess, and deletion controls are policy claims only in this repository; the hosted backend implementation is absent (`SECURITY.md:57-81`). | Treat the hosted backend as unaudited and outside no-egress certification until its code, deployment configuration, logs, storage, and deletion behavior receive a separate review. |

## Current runtime inventory and access table

`None observed` below means no first-party implementation was found. It is not a guarantee about an
unlocked transitive dependency, operating system, browser, MCP host, mounted remote filesystem, or
external backend.

| Current component | Network, telemetry, external assets, models, downloads | Files, temporary data, mutation | Credentials and logs | `SMART_LAB_INDEX_NO_EGRESS` |
|---|---|---|---|---|
| Local MCP server, `pdf-agent-mcp` (`pdf_mcp/server.py:24-153`) | No first-party outbound client, telemetry, model, embedding, or downloader. `mcp.run()` delegates transport behavior to FastMCP; intended registry transport is stdio (`server.json:7-9`). | Reads caller-supplied PDF/DOCX/profile paths. Export tools create or overwrite caller-supplied XLSX/CSV/JSON paths. No temp files in first-party MCP code. | No app credential. Tool arguments/results can contain paths and document content; MCP-host logging is outside this repository. | Ignored; server starts and all tools remain enabled. |
| PDF parser (`pdf_mcp/extractor.py:25-42`, `58-86`, `168-205`) | None observed. Uses `pdfplumber`; no AI/OCR. | Opens source read-only. Optional import-time `PDF_MCP_ALLOWED_DIR` realpath boundary. No source writes or temp files. CLI/MCP paths have no input/resource bounds. | No credential or explicit logger. Exceptions may contain supplied paths. | Ignored. |
| DOCX parser (`pdf_mcp/docx_extractor.py:17-82`) | None observed. Uses `python-docx`; no model call. | Opens source through `_check_path`; source is not written. Expanded ZIP size and XML complexity are not bounded by first-party code. | No credential or explicit logger. | Ignored. |
| Table exporter (`pdf_mcp/exporter.py:33-53`, `107-192`) | None observed. | Reads parser result; creates parent directories and creates/overwrites explicit XLSX/CSV/JSON output. Source path is only read. Formula-like cells are escaped before CSV/XLSX output (`pdf_mcp/output_safety.py:10-20`). | Returned/printed summaries include resolved input/output path metadata. | Ignored. |
| Profile extraction (`pdf_mcp/profiles.py:204-230`; `pdf_mcp/verified.py:41-64`, `390-580`, `683-708`) | None observed. No model call. The remote `$schema` value is inert in this code but may trigger a downstream fetch. | Reads built-in or local profile JSON (custom file capped at 1 MB), reads and hashes documents, and writes explicit exports. User-supplied regex is compiled and evaluated without a time budget (`pdf_mcp/profiles.py:144-149`; `pdf_mcp/verified.py:177-180`). | Results include hashes, extracted records, evidence, and paths supplied by surrounding callers. No explicit logger. | Ignored. |
| Evaluation CLI (`pdf_mcp/profile_cli.py:30-47`; `pdf_mcp/evaluator.py:63-232`) | None observed. | Reads a local manifest, profiles, source documents, and expected values. Optional report output contains aggregate metrics/hashes rather than cell values. Prints that report to stdout. | No credentials. Stdout may be captured by a caller; designed report excludes extracted/expected cells (`pdf_mcp/evaluator.py:216-232`). | Ignored. |
| Export/profile CLIs (`pdf_mcp/cli.py:9-33`; `pdf_mcp/profile_cli.py:11-27`) | None observed. | Read explicit inputs and create/overwrite explicit outputs. | Print resolved output paths, decisions, counts, and warnings. No credentials. | Ignored. |
| Local browser app, `pdf-mcp-app` (`pdf_mcp/web_app.py:162-387`) | Binds `127.0.0.1` only; browser API calls are same-origin; CSP has `connect-src 'self'` (`pdf_mcp/web_app.py:336-342`). `webbrowser.open()` opens the loopback URL. No automatic external fetch, telemetry, model, or download. GitHub links require a user click. | Receives up to 25 MB over loopback, writes a plaintext temporary input and output, then context cleanup runs. Prepared outputs remain in process memory for up to 30 minutes, max five/100 MB. A process crash can leave temp data. Does not alter selected source because the browser supplies bytes. | Random in-page session token gates mutation/download APIs (`pdf_mcp/web_app.py:51-79`, `190-200`, `318-320`). Debug request log may include filename query; exceptions log a traceback. | Ignored. Local behavior happens to be compatible except external links/schema and lack of global enforcement. |
| Desktop package (`scripts/build_desktop_app.py:36-161`) | Runtime app behavior is the browser-app row. Build smoke test connects only to loopback. PyInstaller and dependency installation are build-time external supply-chain paths. | Build script deletes its dedicated `build/desktop-app`, stages files, and replaces matching release ZIP. One-file builds on Linux/Windows may unpack executable resources into OS temp at launch; no document data is intentionally placed there by the build script. | Smoke child inherits the complete build environment (`scripts/build_desktop_app.py:51-59`), although current app code does not consume build credentials. Startup output is put in a temporary file. | Not forwarded or tested as a policy. |
| Cloud MCP bridge, `pdf-agent-cloud-mcp` (`pdf_mcp/cloud_server.py:14-55`; `pdf_mcp/cloud_client.py:27-168`) | Explicit HTTPS POST uploads full selected content; GET requests retrieve usage. HTTP is allowed for loopback development. Redirects are disabled. No model call exists client-side; backend behavior is unavailable. | Reads an explicit local PDF/DOCX, caps compressed upload bytes, then streams it to the configured endpoint under a generic filename. No local temp file or source mutation. Remote temp/storage claims are not verifiable here. | Reads `PDF_MCP_CLOUD_API_KEY` and URL from environment; sends key as Bearer header. Tests cover key omission from returned result/error (`tests/test_cloud_client.py:90-121`). Remote access/security logs are unknown. | Ignored. This path violates strict no-egress. |
| Public static website (`docs/index.html:17-18`, `59-74`, `372`; `docs/offers.js:1-70`) | Automatically makes three HTTPS requests to `raw.githubusercontent.com`; visitor network metadata reaches GitHub. Local CSS/images are bundled. No analytics/advertising code found. External links/mailto are user actions. | Browser cache behavior is requested as `no-store` for offers; the site itself does not access local documents or write application files. | No credential. GitHub/hosting infrastructure logs are external and unaudited. | Not applicable to current static site and incompatible with an offline UI if reused unchanged. |
| Stripe administration script (`scripts/create_stripe_payment_links.py:117-181`) | Dry-run path has no network. `--live` invokes Stripe Product, Price, and Payment Link APIs. No document content is involved. | Reads offer JSON. Live `--write` overwrites offer files with IDs/URLs; test mode refuses published-file writes. | Reads `STRIPE_SECRET_KEY` from environment and sets `stripe.api_key`. First-party output excludes the key, but prints created object IDs/URLs. | Ignored; live mode must be prohibited by a no-egress runtime policy. This script should remain an operator-only tool, outside the product process. |
| Fixture generator (`scripts/generate_simulated_customer_evidence.py:78-176`, `411-464`) | None observed. | Creates/replaces synthetic PDF, DOCX, JSON, and report files under a chosen output directory; rewrites generated DOCX ZIP metadata for reproducibility. | Prints generated manifest paths. No credentials. | Ignored; development-only path. |
| Launch validator (`scripts/validate_launch.py:41-54`, `221-283`) | None observed; parses URLs but does not fetch them. | Read-only repository validation. | Prints status/errors. No credentials. | Ignored; development-only path. |
| Manual inspector (`tests/manual/inspect_document.py:19-62`) | None observed. | Reads explicit documents; no writes. | Prints full path and the first five rows of each table, which can disclose sensitive content to terminals/CI logs. | Ignored; must remain explicitly local/manual and never run automatically on customer material. |
| CI, Pages, release workflows (`.github/workflows/*.yml`) | Deliberate GitHub/PyPI/MCP Registry/package-index egress. Publish uses OIDC and GitHub token; registry binary is downloaded via unverified `curl | tar` (`.github/workflows/publish.yml:105-151`). | CI checks out source, builds artifacts, and publishes site/packages/releases. | GitHub-managed token/OIDC. Runner and action logs are external. No customer files should enter these workflows. | Not a runtime control. No-egress deployments must be built from preverified offline artifacts, not run these workflows onsite. |
| Hosted extraction backend | Implementation absent. | Claims of subprocess isolation, temporary deletion, metrics retention, and storage behavior exist in policy only (`SECURITY.md:64-81`, `PRIVACY.md:24-42`). | Infrastructure credentials/logs/telemetry cannot be inspected. | Outside and incompatible with strict no-egress. |

## Cross-cutting current facts

### Network and telemetry

- **CURRENT FACT:** First-party network-capable Python imports are `httpx` in the cloud bridge,
  `stripe` in the operator script, loopback HTTP/socket utilities in the desktop build smoke test, and
  the loopback HTTP server/browser opener in the local app.
- **CURRENT FACT:** No Sentry, OpenTelemetry, analytics, advertising, usage beacon, auto-update, model
  provider, embedding provider, or vector-database client appears in first-party runtime code.
- **CURRENT FACT:** The static website performs automatic GitHub requests despite having no analytics
  SDK (`docs/offers.js:58-70`). The installed local web UI does not include that script.
- **ASSURANCE GAP:** FastMCP is specified only as `>=2.0`, and direct parser dependencies also have
  open-ended ranges (`pyproject.toml:14-21`). Their exact future runtime behavior is not controlled by
  this repository.
- **ASSURANCE GAP:** An in-process Python convention is not a sandbox. A malicious or compromised
  plugin can import `socket`, spawn a process, use native code, or write through host permissions.
  Built-in-module policy plus tests provides regression control; an OS firewall/process boundary is
  required for a strong adversarial no-egress guarantee.

### External assets and schema references

- **CURRENT FACT:** Local app JS/CSS/HTML are package data (`pyproject.toml:42-44`) and are served from
  local resources (`pdf_mcp/web_app.py:96-97`, `174-184`). The CSP blocks non-self connections and
  scripts.
- **CURRENT FACT:** The public website's principal image, CSS, and examples are repository assets, but
  offer metadata is fetched from GitHub and links lead to GitHub, Stripe/email, and downloads.
- **CURRENT FACT:** `server.json:2` and extraction JSON contain remote schema identifiers. Repository
  code does not dereference them.

### Models and automatic downloads

- **CURRENT FACT:** No inference or embedding implementation exists. No runtime code downloads a
  model, package, tokenizer, OCR data, or domain pack.
- **CURRENT FACT:** Package installation and CI/build processes download dependencies; that is not an
  automatic document-processing action, but it prevents reproducible air-gapped installation without
  a prepared bundle.
- **REQUIREMENT:** A missing local model in no-egress mode must produce `MISCONFIGURED` or
  `UNAVAILABLE`; it must never trigger a Hugging Face, Ollama, package-manager, or arbitrary URL
  download.

### File access, source mutation, and provenance

- **CURRENT FACT:** PDF/DOCX parsers open sources for reading. No current parser edits the source.
- **CURRENT FACT:** Exporters intentionally create directories and overwrite an explicit destination
  (`pdf_mcp/exporter.py:167-177`; `pdf_mcp/verified.py:683-698`). Smart Lab Index must not place these
  outputs inside indexed source roots by default.
- **CURRENT FACT:** `PDF_MCP_ALLOWED_DIR` protects both reads and writes through one boundary, is
  optional, and is captured when `pdf_mcp.extractor` is imported (`pdf_mcp/extractor.py:13-36`). It is
  not a connector permission model and does not separate sources, state, exports, and temp data.
- **CURRENT FACT:** `.gitignore:10-11` excludes manual/private evaluation directories, but ignore rules
  are not a data-loss-prevention boundary.
- **REQUIREMENT:** The filesystem connector must use read-only operations, track source identity and
  permission metadata, isolate inaccessible files, and prove source size/hash/mtime/mode are unchanged
  after success, failure, cancellation, and re-indexing.

### Temporary files and memory

- **CURRENT FACT:** Browser uploads are copied to `TemporaryDirectory`; generated outputs are then
  loaded into memory. Normal context exit removes the directory. Memory entries expire lazily when a
  download is added/read and are cleared on graceful app shutdown (`pdf_mcp/web_app.py:51-93`,
  `234-262`, `384-386`).
- **ASSURANCE GAP:** Abrupt termination cleanup, startup scavenging, secure deletion, disk encryption,
  swap/core-dump exposure, and Windows ACLs are not controlled by this code. Secure deletion cannot be
  promised reliably on modern filesystems; minimize retention and rely on encrypted storage.
- **REQUIREMENT:** Smart Lab Index must use separate configured roots for immutable sources, durable
  Core state, exports, and application temp. Temp filenames should be opaque; directories/files should
  be owner-only where supported; content must not be written to logs.

### Credentials and logs

- **CURRENT FACT:** Runtime credentials are the cloud API key and operator-only Stripe key. Workflow
  credentials are GitHub token/OIDC. Static secret-pattern review found only obvious test placeholders,
  not a committed live credential.
- **CURRENT FACT:** Cloud request code disables redirects and does not include keys in its explicit
  error messages. The configured service still receives the key and ordinary network metadata.
- **ASSURANCE GAP:** There is no shared secret-reference type, log filter, audit-event redaction, or
  guarantee that external MCP hosts, browsers, runners, proxies, or hosted infrastructure do not log
  paths/content.
- **REQUIREMENT:** Module configuration and index-run snapshots must store secret references or
  redacted presence state, never secret values. Secrets must not appear in module health, exception
  messages, provenance, audit events, exports, or support bundles.

## Planned module-category security requirements

The following table is a **target contract**, not a claim that these modules exist. For the first
iteration, `SMART_LAB_INDEX_NO_EGRESS=true` should conservatively allow only `NONE` and explicitly
declared `LOOPBACK` access. Direct LAN/cloud connectivity requires a later, separate endpoint policy;
it must not silently weaken strict no-egress.

| Planned category | Expected access declaration | Strict no-egress behavior | Required controls |
|---|---|---|---|
| Core domain, repositories, registry, events, audit | Network `NONE`; read/write Core state; no source mutation | Allowed | Core owns policy and durable writes. Events carry IDs/references where possible, not entire documents. Audit records module/version/config hash without secret values or extracted content by default. |
| `connector.filesystem` | Network `NONE`; configured source roots `READ`; Core state `WRITE` through service only | Allowed | Realpath/root confinement, symlink policy, read-only opens, incremental hash/change/delete tracking, inaccessible-file isolation, permission metadata, source mutation tests. Detect/document remote mounts as an assurance boundary. |
| `connector.smb`, `connector.nfs` direct clients | Network `CONFIGURED_ENDPOINT`; source credentials; source `READ` | Blocked in strict mode | No start/DNS/login when blocked. A future internal-endpoint mode needs exact allowlists, TLS/auth requirements, redirect prohibition, and documented data perimeter. A filesystem connector over an OS-mounted share cannot independently prove the mount is local. |
| SharePoint, OneDrive, Google Drive, REST, cloud SQL, and vendor SaaS connectors | Network `EXTERNAL`; OAuth/API credentials; remote metadata/content | Blocked | No token lookup/refresh, discovery, telemetry, or request when blocked. Preserve permission metadata. Explicit user/admin enablement outside no-egress. No write-back in first iteration. |
| Internal SQL/LIMS/QMS/ELN/CMMS/ERP connectors | Network `CONFIGURED_ENDPOINT` or local socket; credentials; remote `READ` | Block direct network in strict MVP; local Unix socket/loopback only if explicitly declared | Prepared/read-only queries, endpoint allowlist, bounded results, no redirects/fallback, permission/provenance preservation, health check that does not leak secrets. |
| `parser.pdf`, `parser.docx`, `parser.xlsx`, `parser.csv`, `parser.txt` | Network `NONE`; source-record content `READ`; private temp optional | Allowed | Normalized output only; size/page/row/cell/expanded-archive/CPU/memory/time limits; no macros or external link resolution; no source writes; parser version in provenance; failure becomes an issue. |
| Future image/email/HTML/PPTX/OCR parsers | Network `NONE`; local model/data path if needed | Allowed only with all resources preinstalled | Disable external entity/resource loading, remote image/link fetching, macros, scripts, and automatic OCR/language-data downloads. Treat active content as data. |
| Classifiers (`rules`, filename, spreadsheet structure) | Network `NONE` | Allowed | Bounded deterministic inputs; version all rules; no content logging. |
| Entity/relationship/metadata extractors | Network `NONE` unless separately backed by inference | Allowed deterministic modules only | Produce candidates/assertions through Core contracts; preserve provenance; validate output; never execute source text or mutate source/resolved state directly. |
| Resolvers (identifier, alias, normalized name, fuzzy) | Network `NONE` | Allowed | Bounded candidate sets; retain evidence from every stage; no silent merge; human-review threshold; version algorithm/config. |
| Issue rules and domain packs | Network `NONE` | Allowed | Pure/bounded reads through Core services; issues reference evidence; configuration cannot contain executable code; no hidden module imports. |
| `inference.ollama` | Network `LOOPBACK` to exact configured port or local socket; local model | Allowed only if loopback is explicitly enabled and model already exists | Validate resolved address as loopback, disable redirects, no discovery/download/pull, structured schema validation, bounded prompt/output, content-free logs, no external fallback. |
| `inference.llama_cpp` | Network `NONE`; local model file `READ`; CPU/GPU/memory | Allowed | Model path confined to approved model root, checksum/version recorded, bounded resources, no model download, no native extension network use. |
| External inference provider | Network `EXTERNAL`; API credential; prompts/content leave environment | Blocked | Module cannot initialize, read content, or obtain credentials. Never selected as fallback. Health is `BLOCKED_BY_POLICY`. |
| Local embedding module | Network `NONE`; local model file `READ`; Core vector state `WRITE` | Allowed if artifact is preinstalled | Force library offline/local-files-only settings, record model/checksum/dimension, no cache miss download, bounded batches, no raw text in logs. |
| External embedding module | Network `EXTERNAL`; credential; text/metadata leave environment | Blocked | Same pre-read/pre-DNS refusal and no-fallback requirements as external inference. |
| Lexical/entity search | Network `NONE`; Core index `READ` | Allowed | Query logs off or redacted by default; enforce future source permissions; bounded queries/results. |
| Semantic/hybrid search | Network depends on embedding backend | Allowed only when every dependency is compatible | Registry resolves declared capability dependency. Semantic search becomes `BLOCKED_BY_POLICY` or `MISCONFIGURED`; it must not switch providers silently. |
| UI modules | `LOOPBACK` server; bundled assets | Allowed | Capability-driven local routes, same-origin APIs, CSP, no CDN/fonts/analytics/update checks, no remote schema fetch. External links disabled or clearly separated in strict mode. |
| Export/report/visualization modules | Network `NONE`; explicit export root `WRITE` | Allowed | Formula/active-content defense, no implicit source-directory writes, atomic output, clear overwrite policy, permission-aware content, provenance included. |
| Authentication/access-control modules | Local storage/socket or declared endpoint | Only local/offline implementations allowed | No cloud identity fallback. Preserve source permissions. Credentials are references. An unavailable identity provider fails closed rather than granting broader access. |
| External plugins/installers | Installation may require network; plugin code has process privileges | Runtime installation blocked | Install only from admin-approved, signed/checksummed offline packages. Validate manifest before import. Treat third-party in-process plugins as trusted code unless isolated by OS process controls. No marketplace in MVP. |

## Required module security manifest

**REQUIREMENT:** Every module, including built-ins, must declare at least:

- stable module ID, type, version, Core compatibility, dependencies, and capabilities;
- `network_access`: `NONE`, `LOOPBACK`, `CONFIGURED_ENDPOINT`, or `EXTERNAL`;
- exact endpoint configuration fields and whether DNS, redirects, or discovery are used;
- `no_egress_compatible` and the reason, validated against the network declaration rather than trusted
  blindly;
- source, state, model, temp, and export file access (`READ`, `WRITE`, paths/roots);
- credentials required by reference/name, never values;
- data classes transmitted: source bytes, extracted text, metadata, embeddings, prompts, or counters;
- telemetry/analytics behavior and retention;
- external assets, subprocesses, native code, package/model/content auto-download behavior;
- expected CPU, RAM, GPU, temp, and durable-storage use;
- log fields and redaction classification;
- configuration schema and health-check behavior.

Unknown fields, missing security fields, inconsistent combinations, undeclared capability dependencies,
and an invalid manifest must prevent module enablement. A module must not be imported merely to inspect
its manifest if import-time code can perform I/O; manifests must be data-only.

## Fail-closed no-egress contract

The following behavior is required for the first Smart Lab Index iteration.

1. **Single immutable policy.** Core parses `SMART_LAB_INDEX_NO_EGRESS` before module discovery or
   configuration-secret resolution. Missing means normal mode. Explicit true/false values are
   documented; any present but unrecognized value aborts startup rather than defaulting to false.
2. **Conservative network rule.** Strict mode permits no non-loopback socket. Loopback is permitted
   only for a module that declares `LOOPBACK` and is explicitly enabled. Decide policy before DNS;
   hostname resolution, proxies, redirects, and environment-derived endpoints cannot escape it.
3. **Registry enforcement.** Incompatible modules cannot initialize or start. They report
   `BLOCKED_BY_POLICY`, not merely `DEGRADED`. Required dependants are also blocked with an explicit
   dependency reason; optional failures do not abort deterministic indexing.
4. **Call-time enforcement.** Core network/inference/embedding clients recheck policy at invocation.
   This prevents stale objects or configuration reloads from bypassing startup checks.
5. **No fallback.** Local inference, embedding, search, parser, or connector failure never selects an
   external provider. Missing local artifacts return a bounded error and module health state.
6. **No automatic acquisition.** Runtime cannot invoke `pip`, package managers, model pulls, URL
   downloads, plugin installation, remote schema resolution, or update checks. Offline artifacts are
   installed by an administrator and checksum-verified before startup.
7. **Subprocess propagation.** Every parser/model child receives the immutable no-egress policy, a
   scrubbed environment, bounded resources, and no unnecessary credentials. Strong deployments also
   deny network at the OS/container/firewall layer.
8. **Read-only sources.** Connector code receives a read-only source abstraction. Core state, temp,
   cache, and exports use distinct roots. No output or temp file is placed in a source root by default.
9. **Content-safe observability.** Index runs retain module/version/counters/status and bounded error
   codes. Logs and audit events exclude source bytes, extracted text/cells, prompts, embeddings,
   credentials, and full paths by default.
10. **Bundled UI.** All runtime UI assets are local. Strict mode does not automatically load remote
    offers, fonts, scripts, images, schemas, support widgets, or analytics, and does not claim an
    external link is part of the offline product.
11. **Explicit operator boundary.** Commerce, release publishing, public website hydration, and hosted
    processing remain separate operator/deployment tools, not importable runtime modules enabled in a
    local index process.
12. **Truthful health/audit.** Index-run records include policy mode and the exact enabled module
    versions. A blocked module is visible. No external action is reported as local, and no unaudited
    hosted retention claim is inherited by Core.

For a strong guarantee, pair application enforcement with outbound firewall denial for the Smart Lab
Index process/user. Python module boundaries prevent accidental egress; they do not contain malicious
in-process code.

## First-iteration enforcement requirements

These are release gates for the modular foundation.

- [ ] `SLI-SEC-01`: Add a Core `SecurityPolicy` that parses and exposes immutable no-egress state.
- [ ] `SLI-SEC-02`: Add data-only module manifests with mandatory resource/security declarations.
- [ ] `SLI-SEC-03`: Registry validation rejects incompatible/invalid modules before importing their
  implementation or reading credentials.
- [ ] `SLI-SEC-04`: Mark the existing cloud bridge/external provider capability as blocked and make it
  refuse before path resolution/file open when no-egress is true.
- [ ] `SLI-SEC-05`: Keep local browser/API binding on loopback, bundle all assets, and remove automatic
  remote loads from any Smart Lab Index UI.
- [ ] `SLI-SEC-06`: Implement separate configured source, state, export, model, and private temp roots;
  source roots are read-only-first.
- [ ] `SLI-SEC-07`: Put every parser behind the normalized parser contract with byte, expanded-size,
  structural, time, memory, and output limits plus per-record failure isolation.
- [ ] `SLI-SEC-08`: Add a redacting structured logger/audit writer and prohibit content/secrets in
  default observability.
- [ ] `SLI-SEC-09`: Add no-fallback and local-files-only inference/embedding interfaces even before an
  AI implementation is enabled.
- [ ] `SLI-SEC-10`: Produce a pinned dependency inventory, SBOM, hashes, and documented offline install
  process. No runtime package/model download code is permitted.
- [ ] `SLI-SEC-11`: Run no-egress tests against the packaged desktop/application artifact, not only
  source imports.
- [ ] `SLI-SEC-12`: Document the OS firewall/service-account controls needed to turn application
  policy into an adversarial network guarantee.

## Required test cases

| Test ID | Setup / action | Required result |
|---|---|---|
| `NE-T001` | Set `SMART_LAB_INDEX_NO_EGRESS=true`, configure cloud URL/key, and invoke cloud extraction with file-open, DNS, socket, and HTTP spies. | `BLOCKED_BY_POLICY`; zero path resolution/file opens, credential reads, DNS, sockets, or HTTP calls. |
| `NE-T002` | Set the variable to an unrecognized value such as `tru`. | Startup fails with a bounded configuration error; mode never defaults to off. |
| `NE-T003` | Register manifests for `NONE`, `LOOPBACK`, `CONFIGURED_ENDPOINT`, and `EXTERNAL` test modules. | Strict mode enables only compatible declarations; blocked modules are never imported/initialized. |
| `NE-T004` | Make an enabled module depend on a blocked external capability. | Dependant is blocked with dependency evidence; no hidden fallback is selected. |
| `NE-T005` | Fail a local inference/embedding health check while an external provider is configured. | Deterministic indexing continues where possible; external provider receives zero calls; issue/health is recorded. |
| `NE-T006` | Configure a missing local model/tokenizer/embedding artifact and intercept network/package-manager subprocesses. | Module is `MISCONFIGURED`/`UNAVAILABLE`; no download, pull, install, DNS, socket, or subprocess occurs. |
| `NE-T007` | Start the local UI in strict mode and drive all workflows with browser request interception. | Every automatic request is loopback/same-origin; no CDN, GitHub, schema, update, analytics, or telemetry request occurs. |
| `NE-T008` | Repeat `NE-T007` against each packaged desktop artifact. | Same result; policy survives packaging and child-process startup. |
| `NE-T009` | Attempt direct IPv4, IPv6, DNS name, proxy-environment, redirect, and DNS-rebinding network paths from a built-in module. | Non-loopback destinations fail closed; redirects/proxies cannot bypass the policy. |
| `NE-T010` | Run a declared loopback Ollama-style fake provider on `127.0.0.1`, then make it redirect externally. | Initial loopback call is allowed only when configured; external redirect is rejected. |
| `NE-T011` | Snapshot source file bytes/hash, size, mtime, mode, and tree entries; index success, parser failure, cancellation, and incremental rerun. | No source attribute/content/tree mutation. Only Core state/temp changes in their separate roots. |
| `NE-T012` | Index a source tree containing symlinks outside root, permission-denied files, disappearing files, and a known remote-mount fixture where detectable. | No root escape; failures are isolated and provenance/issues are bounded; policy limitation for mounts is explicit. |
| `NE-T013` | Feed oversized PDF, huge-page PDF, DOCX/XLSX compressed bomb, oversized XML/shared strings, huge CSV field/row count, and parser hang fixture. | Per-file bounded failure and parser issue; run continues; CPU/RAM/temp/output limits hold. |
| `NE-T014` | Put canary source text, filename/path, prompt, embedding values, cloud key, database password, and bearer token through success/error/health paths. | Canary values do not appear in logs, audit events, module health, index-run summaries, crash report, or support bundle. |
| `NE-T015` | Interrupt parsing normally and forcibly; restart application after stale temp fixtures. | Normal cleanup succeeds; stale application-owned temp is safely scavenged; source and unrelated temp files are untouched. |
| `NE-T016` | Enable two parser modules, make one throw, and process multiple records. | Remaining records/modules continue; bounded `PARSING_FAILURE` issue preserves source/module/version evidence. |
| `NE-T017` | Validate every built-in manifest and introduce missing/unknown/inconsistent security fields. | Valid manifests load; invalid manifests fail before implementation import. |
| `NE-T018` | Run full deterministic index with every optional network/AI/semantic module disabled. | Entities, assertions, provenance, lexical/entity search, issues, and index-run audit remain usable offline. |
| `NE-T019` | Scan source and repository descriptors before/after run while monitoring write syscalls. | No write targets source roots; writes are confined to declared state/temp/export roots. |
| `NE-T020` | Install and run from the documented offline artifact with all network denied. | Installation/start/index/search/export work without package, model, schema, asset, or update downloads. |
| `NE-T021` | Spawn parser/model subprocess under strict mode and inspect its environment/permissions/network. | Policy is inherited; unrelated secrets/proxy variables are absent; resource/network restrictions are active. |
| `NE-T022` | Generate extraction/index JSON and open it through the product's own validation path with network interception. | Schema validation uses bundled schema/URN and performs no remote fetch. |
| `NE-T023` | Capture source permission metadata through filesystem connector and query as two synthetic principals. | Metadata is retained; unsupported enforcement is clearly marked rather than granting an implied access guarantee. |
| `NE-T024` | Run a socket-level test with outbound firewall denial in CI or a dedicated integration environment. | Complete no-egress suite passes; any unexpected connection attempt fails the build and identifies module/process. |

Existing tests provide partial coverage only: local browser session/origin/CSP behavior
(`tests/test_web_app.py:79-113`, `212-219`), cloud HTTPS/generic filename/key non-disclosure
(`tests/test_cloud_client.py:71-121`), and spreadsheet formula defense
(`tests/test_exporter.py:57-59`, `122-136`). There are currently no tests for the Smart Lab Index
environment variable, global socket denial, module security metadata, source immutability, parser
resource exhaustion, log redaction, stale temp cleanup, offline model behavior, or packaged no-egress
operation.

## Baseline conclusion

The reusable document-processing code is suitable to become local parser modules because its
first-party implementation is deterministic, source-read-only, model-free, and contains no explicit
outbound client. The local browser app also provides a solid bundled, loopback-only UI baseline.

Those properties are currently conventions attached to specific paths, not a Core-enforced security
contract. Smart Lab Index should first implement one immutable security policy, one validated module
security manifest, one registry enforcement point, separated filesystem roots, bounded parsers, and
the no-egress tests above. External/cloud modules must remain visible but blocked, with no fallback.
Only after those controls pass against packaged artifacts should the product claim fail-closed
`SMART_LAB_INDEX_NO_EGRESS=true` behavior.

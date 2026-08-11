# Organization Coupling Audit

## Scope and method

This audit searched tracked text, configuration, tests, generated fixtures, website content, and release
metadata for organization-, customer-, geography-, language-, vendor-, and operator-specific behavior.
It also inspected extracted text and embedded metadata from every tracked PDF, DOCX, and XLSX file.

The distinction used here is important:

- **Customer coupling** changes product behavior for one laboratory or institution.
- **Domain coupling** encodes assumptions about a category such as laboratory reports.
- **Product/operator coupling** identifies this repository, product, seller, or distribution channel.

Only the first category violates the universal-product requirement directly. The other two still need
intentional placement outside the future small Core.

## Conclusion

No real customer-specific production logic or real customer dataset was found. No hospital,
university, company, laboratory, LIMS, QMS, CMMS, ELN, ERP, room convention, asset convention, or
country-specific workflow is encoded in the document-processing runtime.

The repository does contain:

1. an explicitly fictional laboratory-style evaluation pack;
2. a generic laboratory certificate-of-analysis profile shipped as a built-in default;
3. extensive `pdf-mcp`, repository-owner, seller, email, GitHub, Stripe, and release-channel branding;
4. commercial/legal material tied to the current operator; and
5. hardcoded assumptions about the current product's PDF/DOCX conversion use case.

The fictional data is acceptable as test data. The laboratory profile belongs in an optional document
intelligence or `domain.general_lab` module, not in Smart Lab Index Core. Product/operator metadata
belongs in distribution and commercial configuration, not runtime domain logic.

## Data and fixture audit

### Synthetic invoice sample

The public sample contains generic `Widget`, `Gadget`, and `Bolt` line items and is labeled
`synthetic_regression` in [`evaluations/sample-invoice.json:1`](evaluations/sample-invoice.json#L1).
The corresponding expected values are visible in
[`evaluations/sample-invoice.json:10`](evaluations/sample-invoice.json#L10). PDF metadata is anonymous
and identifies ReportLab as the producer; no person or organization is embedded.

### Fictional laboratory-style pack

The larger fixture set uses the synthetic name `Northstar Water Operations`. Its documentation states
that the organization is fictional and that no customer supplied, approved, used, or paid for the
documents ([`evaluations/simulated-customer/README.md:1`](evaluations/simulated-customer/README.md#L1)).
It explicitly limits claims to deterministic authored regression coverage
([`evaluations/simulated-customer/README.md:53`](evaluations/simulated-customer/README.md#L53)).

The generator embeds that fictional classification in the profile description and uses deterministic
metadata ([`scripts/generate_simulated_customer_evidence.py:20`](scripts/generate_simulated_customer_evidence.py#L20),
[`scripts/generate_simulated_customer_evidence.py:25`](scripts/generate_simulated_customer_evidence.py#L25),
[`scripts/generate_simulated_customer_evidence.py:137`](scripts/generate_simulated_customer_evidence.py#L137)).
Tracked DOCX fixture metadata names `pdf-mcp synthetic fixture generator`; tracked PDF fixture metadata
is anonymous with synthetic titles. No real organization metadata was found.

The fictional pack is safe to retain as legacy parser/profile regression coverage. It should not become
the canonical Smart Lab Index demonstration because it tests analytical-result rows rather than the
entity/assertion conflict scenario in the product vision.

### Private-data controls

The repository ignores `evaluations/private/` and `tests/manual/files/`
([`.gitignore:10`](.gitignore#L10)). Manual test guidance says private invoices and laboratory reports
must not be committed ([`tests/manual/README.md:1`](tests/manual/README.md#L1)). Tests also enforce that
the simulated evaluation cannot be presented as real customer evidence
([`tests/test_simulated_evidence.py:44`](tests/test_simulated_evidence.py#L44)).

## Production domain coupling

### Laboratory profile as a default

`extract_with_profile()` defaults to `lab-coa-v1`
([`pdf_mcp/verified.py:390`](pdf_mcp/verified.py#L390)). The built-in profile assumes analyte, result,
and unit columns for laboratory reports and certificates of analysis
([`pdf_mcp/profile_templates/lab-coa-v1.json:3`](pdf_mcp/profile_templates/lab-coa-v1.json#L3),
[`pdf_mcp/profile_templates/lab-coa-v1.json:12`](pdf_mcp/profile_templates/lab-coa-v1.json#L12)).

This is broad laboratory-domain configuration, not customer coupling. It is nevertheless inappropriate
as a Core default for a universal entity index. Move it to `domain.general_lab` or a document-profile
module and require explicit profile selection where profile extraction remains exposed.

### Fixed built-in profile set

`tests/test_profiles.py` asserts that the exact built-in set is `invoice-lines-v1` and `lab-coa-v1`
([`tests/test_profiles.py:25`](tests/test_profiles.py#L25)). This makes tests resist extension through
registration. Future tests should assert required module/profile presence and uniqueness rather than an
exact global set.

### Converter-specific product assumptions

The local UI hardcodes PDF/DOCX input, XLSX/CSV/JSON output, a multipage-table option, and converter-only
navigation ([`pdf_mcp/web_app.py:30`](pdf_mcp/web_app.py#L30),
[`pdf_mcp/web_ui/index.html:23`](pdf_mcp/web_ui/index.html#L23),
[`pdf_mcp/web_ui/index.html:53`](pdf_mcp/web_ui/index.html#L53)). These are product-scope assumptions,
not organization assumptions. They should become capabilities contributed by document ingestion and
export modules rather than Smart Lab Index Core navigation.

## Product and repository coupling

The following hardcoded identifiers are expected in the current product but must be isolated during a
Smart Lab Index transition:

| Coupling | Evidence | Recommended destination |
| --- | --- | --- |
| Distribution name `pdf-agent-mcp` and six `pdf-*` commands | [`pyproject.toml:5`](pyproject.toml#L5), [`pyproject.toml:31`](pyproject.toml#L31) | Legacy compatibility package and command aliases during migration. |
| Package description and keywords centered on PDF, DOCX, MCP, and agents | [`pyproject.toml:7`](pyproject.toml#L7), [`pyproject.toml:13`](pyproject.toml#L13) | Distribution metadata, eventually replaced for the new product package. |
| MCP server names `pdf-extractor` and `pdf-cloud-extractor` | [`pdf_mcp/server.py:24`](pdf_mcp/server.py#L24), [`pdf_mcp/cloud_server.py:14`](pdf_mcp/cloud_server.py#L14) | Optional legacy MCP adapter configuration. |
| Environment prefix `PDF_MCP_*` | [`pdf_mcp/extractor.py:15`](pdf_mcp/extractor.py#L15), [`pdf_mcp/cloud_client.py:35`](pdf_mcp/cloud_client.py#L35) | Compatibility configuration adapter; new Core settings should use one Smart Lab Index schema. |
| Hardcoded extraction-result schema URL under the owner's repository | [`pdf_mcp/verified.py:550`](pdf_mcp/verified.py#L550) | Versioned schema registry/configuration, not extraction logic. |
| Registry identity and repository URL | [`server.json:2`](server.json#L2) | Release metadata only. |
| GitHub help and source links in the local UI | [`pdf_mcp/web_ui/index.html:17`](pdf_mcp/web_ui/index.html#L17), [`pdf_mcp/web_ui/index.html:138`](pdf_mcp/web_ui/index.html#L138) | Branding/help configuration, removable in no-egress mode. |
| User-Agent `pdf-agent-cloud-mcp/<version>` | [`pdf_mcp/cloud_client.py:92`](pdf_mcp/cloud_client.py#L92) | Hosted integration module only. |
| Desktop archive and executable names | [`scripts/build_desktop_app.py:94`](scripts/build_desktop_app.py#L94) | Packaging configuration. |

None of these identifiers should leak into future entity IDs, assertions, predicates, module contracts,
or database migrations.

## Operator and commercial coupling

The current seller/operator name and email appear in paid-offer JSON, hosted-beta metadata, privacy and
terms, README links, release instructions, and Stripe tooling. Examples include:

- [`offers/sample-conversion.json:5`](offers/sample-conversion.json#L5);
- [`beta/free-hosted-beta.json:6`](beta/free-hosted-beta.json#L6);
- [`PRIVACY.md:44`](PRIVACY.md#L44);
- [`RELEASING.md:8`](RELEASING.md#L8); and
- [`scripts/create_stripe_payment_links.py:15`](scripts/create_stripe_payment_links.py#L15).

This is legitimate operator/distribution configuration and does not currently affect extraction
results. It is tightly bound to launch validation and website behavior, however. For example,
`scripts/validate_launch.py` encodes fixed offer IDs, retention, quotas, evidence metrics, and seller
requirements ([`scripts/validate_launch.py:57`](scripts/validate_launch.py#L57),
[`scripts/validate_launch.py:122`](scripts/validate_launch.py#L122)).

These commercial assets should remain outside Smart Lab Index Core. If retained in the same repository,
place them under an explicitly separate distribution/commerce boundary and do not load them during
local indexing.

## Geographic and language coupling

Runtime parsing and validation do not select behavior by country or language. Header matching uses
Unicode-aware case folding and profile-supplied aliases
([`pdf_mcp/profiles.py:31`](pdf_mcp/profiles.py#L31)), which is more universal than a fixed English
switch, although built-in aliases and UI copy are English.

The privacy notice refers to the Dutch Data Protection Authority
([`PRIVACY.md:84`](PRIVACY.md#L84)), and paid offers use EUR and VAT terminology
([`offers/sample-conversion.json:11`](offers/sample-conversion.json#L11)). This is current operator/legal
context, not application-domain behavior. It must not be moved into Core configuration defaults.

No room identifier format, building hierarchy, personal-name format, asset-number format, date locale,
LIMS vendor, QMS vendor, SharePoint tenant, network share, or customer endpoint is hardcoded in runtime
extraction logic.

## Vendor and platform coupling

There are implementation dependencies on document and interface vendors/libraries, but no laboratory
system vendor integration:

- PDF behavior directly depends on `pdfplumber` APIs
  ([`pdf_mcp/extractor.py:11`](pdf_mcp/extractor.py#L11));
- DOCX behavior directly depends on `python-docx` and even inspects the private `_tc` object for merged
  cells ([`pdf_mcp/docx_extractor.py:12`](pdf_mcp/docx_extractor.py#L12),
  [`pdf_mcp/docx_extractor.py:43`](pdf_mcp/docx_extractor.py#L43));
- exports directly depend on `openpyxl` ([`pdf_mcp/exporter.py:10`](pdf_mcp/exporter.py#L10));
- MCP adapters directly depend on FastMCP ([`pdf_mcp/server.py:13`](pdf_mcp/server.py#L13)); and
- hosted calls directly depend on HTTPX ([`pdf_mcp/cloud_client.py:11`](pdf_mcp/cloud_client.py#L11)).

These dependencies should be contained inside modules/adapters. In particular, Core models must not
expose `pdfplumber`, `python-docx`, OpenPyXL, FastMCP, Stripe, or HTTPX objects.

## Required cleanup boundaries

1. Keep the fictional evaluation data clearly labeled and outside production configuration loading.
2. Move `lab-coa-v1` into an optional general-laboratory/document-intelligence module and remove it as
   the implicit profile default.
3. Preserve old `pdf-*` commands as compatibility adapters while introducing product-neutral service
   interfaces internally.
4. Move repository URLs, schema base URLs, help links, executable names, seller identity, currency,
   retention policy, and checkout behavior into distribution/commercial configuration.
5. Make terminology labels configurable in UI presentation; keep canonical Core types product-neutral.
6. Add a repository rule that production fixtures must be synthetic and that private data directories
   remain ignored.
7. Add automated scans that fail if fixture metadata contains an unapproved author, organization, email,
   tenant URL, or customer identifier.

## Audit result

| Question | Result |
| --- | --- |
| Real customer production data found? | No. |
| Customer-specific runtime branch or mapping found? | No. |
| Specific laboratory system vendor logic found? | No. |
| Laboratory-domain default found? | Yes: `lab-coa-v1`. |
| Explicitly fictional laboratory-style fixtures found? | Yes: Northstar Water evaluation pack. |
| Product/operator identity hardcoded? | Yes, extensively in adapters, distribution, website, and commerce. |
| Core-safe without separation? | No Core exists yet; future Core must exclude these distribution and domain defaults. |

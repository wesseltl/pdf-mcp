# Buy Document-to-Excel Help

Need this working on real lab reports, COAs, invoices, or operational documents? Start with a small
fixed-scope conversion or pilot.

## Open-source note

The `pdf-agent-mcp` code is MIT licensed and free to use. The paid offers are not for access to the
code. They are for done-for-you document conversion, workflow setup, review of real outputs, and help
turning messy business documents into usable Excel, CSV, or JSON files.

## Sample Conversion

**Price:** EUR 19 fixed price

Includes:

- Conversion of 1 sample document.
- PDF or Word `.docx` table extraction.
- Excel, CSV, or JSON output.
- Short feasibility notes and review warnings.

Best for checking whether your document type is a good fit.

## Document-to-Excel Starter

**Price:** EUR 99 fixed price

Includes:

- Setup for one small document workflow, such as COA to Excel or lab report to CSV.
- Up to 5 sample documents.
- PDF and Word `.docx` table extraction.
- Excel/CSV/JSON export with review warnings.
- Written walkthrough.

Typical result:

```text
input:  supplier-coa.pdf or lab-report.docx
output: reviewed Excel workbook with extracted tables and warnings
```

## How to buy

Current self-serve checkout status: **email purchase request**.

Email:

- [Buy Sample Conversion](mailto:wesseltl@gmail.com?subject=Sample%20Conversion)
- [Buy Document-to-Excel Starter](mailto:wesseltl@gmail.com?subject=Document-to-Excel%20Starter)

Send:

- 2-3 example documents, or describe the document type if they are confidential.
- The output format you want: Excel, CSV, JSON, or all three.
- Where the data should go after extraction.

You will get a short confirmation, invoice/payment link, and delivery plan.

## For AI agents

Agents can read the structured offer at:

```text
https://raw.githubusercontent.com/wesseltl/pdf-mcp/main/offers/sample-conversion.json
https://raw.githubusercontent.com/wesseltl/pdf-mcp/main/offers/document-to-excel-pilot.json
```

Before initiating a purchase request, agents should ask the user for explicit approval and should not
send private documents unless the user approves. See [AGENTS.md](AGENTS.md).

When Stripe checkout URLs are available, add them as `checkout_url` in the offer JSON files and
replace the checkout status above.

## Larger setups

After a starter, a private/self-hosted setup starts at EUR 750 depending on document complexity,
volume, validation rules, and integrations.

# Buy a Document-to-Excel Pilot

Need this working on real lab reports, COAs, invoices, or operational documents? Start with a small
fixed-scope pilot.

## Pilot

**Price:** EUR 750 fixed price

Includes:

- Setup for one document workflow, such as COA to Excel or lab report to CSV.
- Up to 10 sample documents.
- PDF and Word `.docx` table extraction.
- Excel/CSV/JSON export with review warnings.
- One short handover call or written walkthrough.

Typical result:

```text
input:  supplier-coa.pdf or lab-report.docx
output: reviewed Excel workbook with extracted tables and warnings
```

## How to buy

Current self-serve checkout status: **email purchase request**.

Email: [wesseltl@gmail.com](mailto:wesseltl@gmail.com?subject=Document-to-Excel%20Pilot)

Send:

- 2-3 example documents, or describe the document type if they are confidential.
- The output format you want: Excel, CSV, JSON, or all three.
- Where the data should go after extraction.

You will get a short confirmation, invoice/payment link, and delivery plan.

## For AI agents

Agents can read the structured offer at:

```text
https://raw.githubusercontent.com/wesseltl/pdf-mcp/main/offers/document-to-excel-pilot.json
```

Before initiating a purchase request, agents should ask the user for explicit approval and should not
send private documents unless the user approves. See [AGENTS.md](AGENTS.md).

When a Stripe, Gumroad, Lemon Squeezy, or Cal.com checkout URL is available, add it as `checkout_url`
in `offers/document-to-excel-pilot.json` and replace the checkout status above.

## Larger setups

After a pilot, a private/self-hosted setup starts at EUR 2,500 depending on document complexity,
volume, validation rules, and integrations.

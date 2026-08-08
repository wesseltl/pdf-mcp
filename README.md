<!-- mcp-name: io.github.wesseltl/pdf-mcp -->

# pdf-mcp

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/MCP-server-6E56CF)
![License](https://img.shields.io/badge/license-MIT-green)

**Let your AI agent pull text and tables out of PDFs.** An [MCP](https://modelcontextprotocol.io)
server for invoices, reports, and statements, where the data lives in tables the model can't read from
a pasted blob.

When you paste a PDF into a prompt, the columns collapse and the table turns to mush, so the model
guesses at the numbers. This extracts the actual table structure with deterministic code, so the agent
gets clean rows and never invents a cell.

## What it turns a PDF into

A PDF invoice table like this:

```
Item     Qty   Price
Widget    3    12.50
Gadget    1    40.00
Bolt     10     0.25
```

comes back as structured rows (or CSV), not a flattened line of text:

```json
[["Item","Qty","Price"],["Widget","3","12.50"],["Gadget","1","40.00"],["Bolt","10","0.25"]]
```

## The tools it gives an agent

| Tool | What it does |
|---|---|
| `page_count(path)` | How many pages the PDF has |
| `extract_text(path, page)` | Text per page (one page, or the whole doc) |
| `extract_tables(path, page)` | Tables as rows of cells |
| `table_to_csv(path, page, index)` | One table as clean CSV text |

## Quickstart

```bash
pip install "pdf-agent-mcp[mcp]"
```

Add it to your MCP client (e.g. Claude Desktop):

```json
{
  "mcpServers": {
    "pdf": { "command": "pdf-agent-mcp" }
  }
}
```

Now your agent can answer "pull the line items out of this invoice" by reading the PDF, not guessing.

## Also usable from plain Python

```python
from pdf_mcp import extractor

extractor.extract_tables("invoice.pdf")      # {'tables': [{'rows': [...]}], ...}
extractor.table_to_csv("invoice.pdf")        # clean CSV of the first table
extractor.extract_text("report.pdf", page=1)
```

## Tests

```bash
python -m unittest discover -s tests     # builds its own test PDF, runs anywhere
```

## License

MIT

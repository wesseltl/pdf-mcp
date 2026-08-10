<!-- mcp-name: io.github.wesseltl/pdf-mcp -->

# pdf-mcp

![CI](https://github.com/wesseltl/pdf-mcp/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/MCP-server-6E56CF)
![License](https://img.shields.io/badge/license-MIT-green)

**Let your AI agent pull text and tables out of PDFs and Word documents.** An
[MCP](https://modelcontextprotocol.io) server for invoices, reports, statements, and lab documents,
where the data lives in tables the model can't read from a pasted blob.

When you paste a document into a prompt, the columns collapse and the table turns to mush, so the
model guesses at the numbers. This extracts the actual table structure with deterministic code, so the
agent gets clean rows and never invents a cell.

## What it turns a document into

A PDF or Word table like this:

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
| `extract_tables(path, page, merge_multipage)` | Tables as rows of cells, each with an honest assessment (`looks_clean`, `warnings`) flagging ragged or mostly-empty extractions |
| `table_to_csv(path, page, index)` | One table as clean CSV text |
| `extract_docx_text(path)` | Paragraph text from a `.docx` file |
| `extract_docx_tables(path)` | Word tables as rows of cells, with the same assessment fields |
| `docx_table_to_csv(path, index)` | One Word table as clean CSV text |

## Getting started (Claude Desktop)

The fastest way to use this is with an MCP client like Claude Desktop. Three steps:

**1. Install it**

```bash
pip install "pdf-agent-mcp[mcp]"
```

**2. Add it to your client's config**

Claude Desktop's config lives here:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Add the server:

```json
{
  "mcpServers": {
    "pdf": { "command": "pdf-agent-mcp" }
  }
}
```

**3. Restart Claude Desktop.** You'll see a tools icon appear, meaning the server is connected.

That's it. Now ask about any `.pdf` or `.docx` on your machine:

```
You:  Pull the line items out of /Users/me/invoices/2024-001.pdf

Agent (calls extract_tables):
  Item     Qty   Price
  Widget    3    12.50
  Gadget    1    40.00
  Bolt     10     0.25
  (the table extracted cleanly)
```

The agent reads the real table structure instead of a flattened blob, so nothing is misaligned.

> **Restricting file access:** to stop the agent reading anything outside one folder, set
> `PDF_MCP_ALLOWED_DIR`. See [SECURITY.md](SECURITY.md).

## Use it with other MCP clients

The same server works in any MCP client, only the config differs. Use `pdf-agent-mcp` as the command.

**Cursor** — `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (per project). Same shape as Claude
Desktop, and it hot-reloads (no restart):

```json
{ "mcpServers": { "pdf": { "command": "pdf-agent-mcp" } } }
```

**VS Code / GitHub Copilot** — `.vscode/mcp.json`. Note the different key (`servers`, not `mcpServers`)
and the required `type`. Tools only run in Copilot **Agent mode**:

```json
{ "servers": { "pdf": { "type": "stdio", "command": "pdf-agent-mcp" } } }
```

**Windsurf** — `~/.codeium/windsurf/mcp_config.json` (create it if missing). Same shape as Claude
Desktop:

```json
{ "mcpServers": { "pdf": { "command": "pdf-agent-mcp" } } }
```

**Cline** — add it from the extension's MCP settings panel in VS Code (command: `pdf-agent-mcp`).

## Understanding the output

`extract_tables` returns the rows, plus an honest assessment of how reliable each table looks, so you
can trust a clean table and double-check a shaky one:

```json
{
  "page": 1,
  "rows": [ ... ],
  "n_rows": 4,
  "looks_clean": true,
  "column_count": 3,
  "empty_ratio": 0.0,
  "warnings": []
}
```

- **`looks_clean`** — `true` if the table extracted without red flags.
- **`column_count`** — the number of columns, if every row agrees on it (`null` if rows disagree).
- **`empty_ratio`** — fraction of blank cells. A high value often means a bad extraction.
- **`warnings`** — plain-language flags, e.g. *"ragged: rows have [2, 3, 4] columns (grid may be
  misdetected)"* or *"66% of cells are empty"*. PDF tables are genuinely hard (nested/merged cells,
  multi-page), so instead of pretending, the tool tells you when a result is suspect.

## Also usable from plain Python

```python
from pdf_mcp import docx_extractor, extractor

extractor.extract_tables("invoice.pdf")      # {'tables': [{'rows': [...], 'looks_clean': True, ...}]}
extractor.table_to_csv("invoice.pdf")        # clean CSV of the first table
extractor.extract_text("report.pdf", page=1)

docx_extractor.extract_docx_tables("coa.docx")
docx_extractor.docx_table_to_csv("coa.docx")
```

## Tests

```bash
python -m pip install -e ".[test]"
python -m unittest discover -s tests     # builds synthetic PDFs, runs anywhere
```

## License

MIT

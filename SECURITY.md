# Security

This server is designed to be safe to point at real business data. Here is exactly what it does and
does not do.

## What it does

- **Runs locally.** It executes on your own machine as a normal Python process. Your files are read
  where they sit; nothing is uploaded anywhere.
- **Read-only extraction.** The extraction tools only *read* the PDF or Word files you point them at.
- **Explicit exports only.** `export_document_tables` writes a new `.xlsx`, `.csv`, or `.json` file
  only to the output path you provide. It never modifies the source document.
- **No network calls.** The server makes no outbound network requests. Your data cannot be sent
  anywhere because nothing is sent anywhere.
- **No telemetry.** It collects no usage data, no analytics, nothing.
- **Deterministic reading.** The cell values are read by plain tested Python (`pdfplumber` and
  `python-docx`). A language model never reads a value and writes back a "cleaned" one, so nothing is
  invented or altered.
- **Open source (MIT).** Every line is auditable in this repository.

## What you should still be aware of

- **File access scope.** By default the server can read supported document paths and write explicit
  export outputs anywhere the process has OS permission. To lock it down, set the environment
  variable **`PDF_MCP_ALLOWED_DIR`** to a directory: the server will then refuse to read inputs or
  write exports outside that directory (symlink and `..` traversal are blocked too). Example:

  ```json
  { "mcpServers": { "pdf": { "command": "pdf-agent-mcp",
      "env": { "PDF_MCP_ALLOWED_DIR": "/data/documents" } } } }
  ```
- **Prompt injection.** Text inside a document is *data*, not instructions. This server returns cell
  values as structured data; it does not execute anything found inside a file. As always, treat the
  content an agent reads from any document as untrusted input in your own workflow.

## Reporting an issue

Found a security problem? Please open an issue, or email wesseltl@gmail.com.

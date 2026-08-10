# Manual tests with real documents

Put local sample PDFs or Word documents in `tests/manual/files/`. That folder is gitignored so
invoices, lab reports, or other private documents do not get committed.

Run the inspector against one or more files:

```bash
python tests/manual/inspect_document.py tests/manual/files/example.pdf
python tests/manual/inspect_document.py tests/manual/files/example.docx
```

The inspector prints extracted text counts, table counts, merge flags, warnings, and the first few
rows from each table. Use it for real-world regression checks before changing extraction heuristics.

To test the full document-to-file workflow:

```bash
export-document-tables tests/manual/files/example.pdf tests/manual/files/example.xlsx
export-document-tables tests/manual/files/example.docx tests/manual/files/example.xlsx
```

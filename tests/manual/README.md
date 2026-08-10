# Manual tests with real PDFs

Put local sample PDFs in `tests/manual/files/`. That folder is gitignored so invoices, lab reports,
or other private documents do not get committed.

Run the inspector against one or more files:

```bash
python tests/manual/inspect_pdf.py tests/manual/files/example.pdf
```

The inspector prints page count, extracted table counts, merge flags, warnings, and the first few rows
from each table. Use it for real-world regression checks before changing table extraction heuristics.

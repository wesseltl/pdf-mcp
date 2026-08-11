# Smart Lab Index synthetic example

Generate the fixture from the repository root:

```bash
.venv/bin/python scripts/generate_smart_lab_example.py
```

All names and records are synthetic. The generated source folder is read only during
indexing. It deliberately contains two different observed locations for `Freezer-001`
so the conflict rule can demonstrate assertion preservation and provenance.

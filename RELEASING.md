# Releasing

This project publishes to PyPI with GitHub Actions and PyPI Trusted Publishing. That avoids storing a
PyPI API token on a development machine or in GitHub secrets.

## One-time PyPI setup

In the PyPI project settings for `pdf-agent-mcp`, add a trusted publisher:

- Owner: `wesseltl`
- Repository name: `pdf-mcp`
- Workflow name: `publish.yml`
- Environment name: `pypi`

## Release checklist

1. Update the version in `pyproject.toml`, `pdf_mcp/__init__.py`, and `server.json`.
2. Run the tests:

   ```bash
   python -m pip install -e ".[test]"
   python -m unittest discover -s tests
   ```

3. Build and check the distributions:

   ```bash
   python -m pip install build twine
   rm -rf dist build
   python -m build
   python -m twine check dist/*
   ```

4. Commit and push the release changes.
5. Create and push a version tag:

   ```bash
   git tag v0.1.4
   git push origin v0.1.4
   ```

The `Publish` workflow will build the package and upload it to PyPI.

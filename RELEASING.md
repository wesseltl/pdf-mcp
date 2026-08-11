# Releasing

This project publishes to PyPI with Trusted Publishing, then publishes the same `server.json` version
to the MCP Registry with GitHub OIDC. Neither flow stores a registry token in the repository.

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
   evaluate-document-profile evaluations/sample-invoice.json
   evaluate-document-profile evaluations/simulated-customer/development.json
   evaluate-document-profile evaluations/simulated-customer/holdout.json
   ```

3. Build and check the distributions:

   ```bash
   python -m pip install build twine
   rm -rf dist build
   python -m build
   python -m twine check dist/*
   ```

4. Run the paid-beta metadata and launch checks:

   ```bash
   python scripts/validate_launch.py
   ```

5. Commit and push the release changes.
6. Create and push a version tag:

   ```bash
   VERSION=$(python -c 'import pdf_mcp; print(pdf_mcp.__version__)')
   git tag "v$VERSION"
   git push origin "v$VERSION"
   ```

The `Publish` workflow uploads the package to PyPI and, after that succeeds, publishes the matching
metadata to the MCP Registry. The `Pages` workflow deploys the commercial site from `docs/` on every
push to `main`.

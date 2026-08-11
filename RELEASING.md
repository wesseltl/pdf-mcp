# Releasing

This project publishes to PyPI with Trusted Publishing, then publishes the same `server.json` version
to the MCP Registry with GitHub OIDC. Neither flow stores a registry token in the repository.

## One-time PyPI setup

In the PyPI project settings for `pdf-agent-mcp`, add a trusted publisher:

- Owner: `wesseltl`
- Repository name: `pdf-mcp`
- Workflow name: `publish.yml`
- Environment name: `pypi`

After the publisher exists, add the GitHub Actions repository variable
`PYPI_PUBLISH_ENABLED=true`. Leave it unset until then; desktop releases remain independent and
will still publish successfully.

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

   Build and smoke-test the standalone app on the current platform:

   ```bash
   python -m pip install -e ".[desktop-build]"
   python scripts/build_desktop_app.py
   python scripts/build_smart_lab_desktop_app.py
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

The `Publish` workflow builds and smoke-tests the PDF converter and Smart Lab Index standalone apps
on Windows, macOS, and Linux, then creates a GitHub release with those archives and the Python
distributions. The Smart Lab smoke test runs the compiled executable through the complete synthetic
no-egress index. When
`PYPI_PUBLISH_ENABLED=true`, it also uploads the package to PyPI and, after that succeeds, publishes
matching metadata to the MCP Registry. The `Pages` workflow deploys the public site from `docs/` on
every push to `main`.

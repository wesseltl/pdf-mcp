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
   # Windows only; requires Inno Setup 6
   python scripts/build_smart_lab_windows_installer.py
   ```

   The LabOverlay build writes matching SHA-256 manifests. On Windows, the installer build performs
   a silent per-user install, exercises the installed app through the complete synthetic index, and
   uninstalls it before accepting the artifact. The installer has a stable application ID so a newer
   release upgrades the existing installation. It never removes the user's
   `%USERPROFILE%\.laboverlay` data directory.

   Windows and macOS builds are unsigned unless release credentials are configured. The same
   Windows Authenticode identity signs both the application executable and Setup executable. For
   GitHub Actions, use these secrets:

   | Secret | Purpose |
   |---|---|
   | `WINDOWS_CODESIGN_CERTIFICATE_BASE64` | Base64-encoded Authenticode PFX |
   | `WINDOWS_CODESIGN_CERTIFICATE_PASSWORD` | PFX password |
   | `MACOS_CODESIGN_CERTIFICATE_BASE64` | Base64-encoded Developer ID Application P12 |
   | `MACOS_CODESIGN_CERTIFICATE_PASSWORD` | P12 password |
   | `MACOS_CODESIGN_IDENTITY` | Exact Developer ID Application identity |
   | `MACOS_NOTARY_APPLE_ID` | Apple account used by `notarytool` |
   | `MACOS_NOTARY_PASSWORD` | App-specific password for notarization |
   | `MACOS_NOTARY_TEAM_ID` | Apple Developer team ID |

   Set repository variable `DESKTOP_SIGNING_REQUIRED=true` only after the Windows and macOS
   credentials are installed. With that variable enabled, those platform builds fail closed rather
   than publishing unsigned LabOverlay artifacts. macOS notarization runs when all three notary
   credentials are present.

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

The `Publish` workflow builds and smoke-tests the PDF converter and LabOverlay standalone apps
on Windows, macOS, and Linux, then creates a GitHub release with those archives, the Windows Setup
executable, and the Python distributions. The LabOverlay smoke test runs the compiled executable
through the complete synthetic no-egress index; Windows additionally validates install and
uninstall. When
`PYPI_PUBLISH_ENABLED=true`, it also uploads the package to PyPI and, after that succeeds, publishes
matching metadata to the MCP Registry. The `Pages` workflow deploys the public site from `docs/` on
every push to `main`.

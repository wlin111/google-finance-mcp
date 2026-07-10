# Release process

## Build package

This is a pure Python package, so there is no native compile step. To build a
wheel and source distribution:

```bash
python -m pip install build
python -m build
```

Install the built wheel:

```bash
python -m pip install dist/google_finance_mcp-<version>-py3-none-any.whl
```

You can also run the module entry point without relying on the console script:

```bash
python -m google_finance_mcp
```

To build release artifacts locally:

```bash
bash scripts/build-macos-release.sh
bash scripts/build-linux-release.sh
pwsh scripts/build-windows-release.ps1
```

The macOS build script creates an unsigned `pkgbuild` component package and
verifies its installer `Bom` before publishing the `.pkg` artifact. This avoids a
paid Apple Developer ID dependency, but it does not bypass Gatekeeper's trust
checks for downloaded installers.

Release preparation starts from the version in `pyproject.toml`. In the release
pull request, update the README download examples and refresh package metadata:

```bash
python scripts/update-readme-release-version.py v<version>
python -m build
```

When the release pull request lands on `master`,
`.github/workflows/prepare-release.yml` verifies those generated files are
already committed, creates tag `v<version>`, and publishes the GitHub Release for
that tag. The workflow does not push generated commits back to `master`, so it
works with branch protection rules that require changes to go through pull
requests.

GitHub release assets are then built by `.github/workflows/release.yml` for that
release tag. The prepare workflow dispatches the asset builder after publishing
the Release, and the builder uploads the generated files to that Release.

The workflow uploads:

- macOS Apple Silicon (`arm64`) `.pkg`, `.tar.gz`, and `.sha256` files.
- Linux `x86_64` `.tar.gz` and `.sha256` files.
- Windows `x86_64` `.zip` and `.sha256` files.

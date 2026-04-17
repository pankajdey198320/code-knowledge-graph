# Private Package Release Checklist

Use this checklist when publishing `kg-code-rag` to an internal package feed.

## Scope

This checklist assumes:

- the package is distributed internally, not to public PyPI
- MCP repo and scope configuration is provided by MCP host config
- the published artifact is a generic `kg-code-rag` wheel or sdist

## 1. Pre-release checks

- [ ] Confirm the branch contains the intended MCP/runtime changes only.
- [ ] Confirm the package version in `pyproject.toml` has been bumped.
- [ ] Confirm `README.md` reflects any new runtime configuration or packaging behavior.
- [ ] Confirm no repo-specific paths, tokens, or private config files are hard-coded into package source.
- [ ] Confirm `projects.json` is not required for packaged runtime behavior.
- [ ] Confirm local-only folders such as `.venv/`, `data/`, `Neo4_data/`, and cached model assets are not part of the release plan.

## 2. Environment preparation

- [ ] Activate the release virtual environment.
- [ ] Upgrade packaging tools.
- [ ] Install dev dependencies.

Commands:

```bash
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## 3. Quality checks

- [ ] Run the relevant test suite.
- [ ] Run focused tests for packaging-sensitive config behavior.
- [ ] Resolve any failing checks before building artifacts.

Recommended commands:

```bash
python -m pytest test_projects_config.py
```

If you have a broader validation suite for release candidates, run that here as well.

## 4. Build artifacts

- [ ] Clean or review the existing `dist/` output.
- [ ] Build both wheel and source distribution.
- [ ] Confirm the expected files exist in `dist/`.

Command:

```bash
python -m build
```

Expected outputs:

- `dist/kg_code_rag-<version>-py3-none-any.whl`
- `dist/kg_code_rag-<version>.tar.gz`

## 5. Validate artifacts

- [ ] Run `twine check` on the generated artifacts.
- [ ] Inspect package metadata for the correct version and project description.
- [ ] Confirm the package name is `kg-code-rag` and the import package remains `kg_rag`.

Command:

```bash
python -m twine check dist/*
```

## 6. Smoke test install

- [ ] Install the built wheel into a clean environment.
- [ ] Confirm the CLI entry points are available.
- [ ] Confirm the package starts with MCP env-driven configuration.

Suggested commands:

```bash
pip install dist/kg_code_rag-<version>-py3-none-any.whl
kg-mcp --help
kg-index --help
```

For runtime verification, launch the server with representative MCP env vars in a clean shell.

## 7. Publish to internal feed

- [ ] Confirm the target repository URL.
- [ ] Confirm credentials are available through secure environment or credential manager.
- [ ] Confirm GitHub repository or environment secrets are populated for automated publishing.
- [ ] Upload artifacts.
- [ ] Record the published version and feed location.

Command:

```bash
python -m twine upload --repository-url https://your-package-feed.example.com/simple/ dist/*
```

If your internal feed uses a named Twine repository profile, use that instead.

For GitHub Actions, the workflow in `.github/workflows/private-package.yml` expects these secrets:

- `PRIVATE_PYPI_REPOSITORY_URL`
- `PRIVATE_PYPI_USERNAME`
- `PRIVATE_PYPI_PASSWORD`

The publish job is intentionally manual via `workflow_dispatch` so package releases stay explicit.

## 8. Post-publish verification

- [ ] Install the package from the internal feed in a fresh environment.
- [ ] Confirm the installed version matches the intended release.
- [ ] Start at least one MCP server entry using the published package.
- [ ] Verify graph cache creation and MCP tool startup behavior.

Suggested commands:

```bash
pip install --index-url https://your-package-feed.example.com/simple/ kg-code-rag==<version>
pip show kg-code-rag
```

## 9. MCP rollout checks

- [ ] Update MCP server definitions to reference the released environment.
- [ ] Confirm repo-specific MCP env values are correct for each server.
- [ ] Confirm cache directories are writable.
- [ ] Confirm model download or local model availability is acceptable for the target environment.

Typical MCP env to verify:

- `KG_REPO_ROOT`
- `KG_PROJECT_NAME`
- `KG_SCOPE_PATHS`
- `KG_CACHE_DIR`
- `KG_PROJECTS_JSON` or `KG_PROJECTS_FILE` when using multi-scope mode

## 10. Rollback plan

- [ ] Keep the previous known-good wheel version available in the internal feed.
- [ ] Record the last known-good MCP environment or package version.
- [ ] If startup or indexing regresses, pin MCP hosts back to the previous package version.

## Release sign-off

- [ ] Artifacts built successfully.
- [ ] Artifact validation passed.
- [ ] Internal publish succeeded.
- [ ] Fresh install verification succeeded.
- [ ] MCP runtime verification succeeded.
- [ ] Release notes or team notification sent.

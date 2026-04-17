# MCP Packaging Plan

## Goal

Run many MCP servers against different repositories or sub-scopes without storing repo-specific `projects.json` inside the package source tree.

## Recommended packaging model

Ship a single reusable Python package:

- Package name: `kg-code-rag`
- Entrypoint: `python -m kg_rag.mcp_server` or `kg-mcp`
- Contents: parser/runtime code only
- Excluded from packaging decisions: repo-specific scopes, repo roots, user-specific paths

That package is then instantiated multiple times by MCP configuration.

## Deployment shape

1. Build one wheel for `kg-code-rag`.
2. Install it into a shared virtual environment or an internal tool environment.
3. Define one MCP server per repo or per project scope in `.vscode/mcp.json`, user MCP settings, or host-level MCP configuration.
4. Pass repo identity and scope through MCP env vars.

## Why this shape is the right one

- It separates product code from environment-specific deployment state.
- It lets one package support many repositories with no rebuild.
- It works for local development, shared team settings, and CI-hosted MCP setups.
- It avoids carrying confidential repo topology inside the package source.

## Configuration modes

### Mode 1: Single scoped server per MCP entry

Best when you want dedicated tools like `kg-upgrader`, `kg-bladedng`, `kg-workflow`.

Example:

```json
{
  "servers": {
    "kg-upgrader": {
      "type": "stdio",
      "command": "C:/shared/kg/.venv/Scripts/python.exe",
      "args": ["-m", "kg_rag.mcp_server"],
      "cwd": "C:/shared/kg",
      "env": {
        "KG_REPO_ROOT": "W:/git/Bladed",
        "KG_PROJECT_NAME": "Upgrader",
        "KG_SCOPE_PATHS": "BladedX/Upgrader",
        "KG_CACHE_DIR": "C:/shared/kg/data"
      }
    }
  }
}
```

Benefits:

- clean tool names
- no runtime switching needed
- simpler permissions and isolation

### Mode 2: Multi-project server from inline MCP JSON

Best when one MCP entry should expose `list_projects`, `switch_project`, and `index_project` across several named scopes.

Example env payload:

```json
{
  "repo_root": "W:/git/Bladed",
  "cache_dir": "C:/shared/kg/data",
  "projects": {
    "Upgrader": {
      "description": "BladedX Upgrader project",
      "paths": ["BladedX/Upgrader"]
    },
    "BladedNG": {
      "description": "BladedNG including CLI, test, and installer code",
      "paths": ["BladedX"]
    }
  }
}
```

Pass that JSON in `KG_PROJECTS_JSON`, or put it in an external file and point `KG_PROJECTS_FILE` at it.

Benefits:

- one server process can switch between named scopes
- config can live outside the repo and outside the package
- preserves project-management tools for advanced use cases

## Cache strategy

Use a shared cache directory such as `C:/shared/kg/data`.

- Cache filenames should include the logical project name.
- Cache filenames should also include a hash of the repo root.
- This avoids collisions when two repos use the same project name.

## Operational guidance

- Prefer Mode 1 for daily use because it gives the model clearer tool boundaries.
- Use Mode 2 when you explicitly want project switching inside one server.
- Keep secrets and tokens in MCP env or host secret storage, not in package files.
- Keep repo-root and scope configuration in MCP settings, not in source-controlled package defaults.

## Migration from `projects.json`

1. Move repo root and scope definitions into MCP config.
2. Keep `projects.json` only as a local fallback during transition.
3. Once all MCP entries are migrated, remove repo-specific `projects.json` from the packaged deployment.

## Summary

The package should be generic.
The MCP host should own repo selection.
Named project scopes should come from MCP configuration, not from source-embedded runtime files.

For an operational release flow, see [docs/private-release-checklist.md](docs/private-release-checklist.md).

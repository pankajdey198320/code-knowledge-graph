---
name: multi-project-mcp-endpoint-test
description: Launch and validate the Python MCP SSE server with URL-prefixed project routes.
---

# Multi-project MCP endpoint test

Use this skill when validating project routing against a deployment `projects.sample.json`.

## Run from VS Code

Run the `Test Multi-project MCP endpoints` task. It starts a temporary SSE server on port `8010`, tests both URL forms for every configured project, and stops the server when complete.

## Run directly

```powershell
Set-Location ${workspaceFolder}\py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\test_multi_project_endpoints.ps1
```

The script defaults to `C:\Public\Deployment\MCP_server\KG\projects.sample.json`. Override it when needed:

```powershell
.\test_multi_project_endpoints.ps1 -ProjectsFile C:\path\to\projects.sample.json -Port 8011
```

## Expected routes

For each configured project, both routes must return HTTP 200 with `text/event-stream`:

- `/p/{project}/sse`
- `/projects/{project}/sse`

The first request to an uncached project may take longer because it activates or indexes the project. The script uses a ten-second request timeout by default; increase it with `-RequestTimeoutSeconds` for a cold repository.

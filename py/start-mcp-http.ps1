param(
    [string]$ProjectsFile = (Join-Path $PSScriptRoot "projects.sample.json"),
    [string]$ActiveProject = "",
    [switch]$IndexAllProjects,
    [ValidateSet("streamable-http", "sse")]
    [string]$Transport = "streamable-http",
    [string]$Host = "127.0.0.1",
    [int]$Port = 8000,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

function Get-ConfiguredProjectNames {
    param(
        [string]$ConfigPath
    )

    $config = Get-Content -Path $ConfigPath -Raw | ConvertFrom-Json
    if (-not $config.projects) {
        return @()
    }

    return @($config.projects.PSObject.Properties.Name)
}

function Invoke-ProjectIndex {
    param(
        [string]$ProjectName
    )

    Write-Host "Indexing project '$ProjectName' ..."
    & $PythonExe -m kg_rag.cli --project $ProjectName
    if ($LASTEXITCODE -ne 0) {
        throw "Indexing failed for project '$ProjectName'."
    }
}

Set-Location $PSScriptRoot

if (-not $PythonExe) {
    $venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $PythonExe = $venvPython
    }
    else {
        $pythonCommand = Get-Command python -ErrorAction Stop
        $PythonExe = $pythonCommand.Source
    }
}

$resolvedProjectsFile = (Resolve-Path $ProjectsFile).Path
$env:KG_PROJECTS_FILE = $resolvedProjectsFile

if ($ActiveProject) {
    $env:ACTIVE_PROJECT = $ActiveProject
}

Write-Host "Starting KG MCP server over HTTP"
Write-Host "  Python: $PythonExe"
Write-Host "  Projects file: $resolvedProjectsFile"
if ($ActiveProject) {
    Write-Host "  Active project: $ActiveProject"
}
Write-Host "  Transport: $Transport"
Write-Host "  Host: $Host"
Write-Host "  Port: $Port"

if ($Transport -eq "streamable-http") {
    Write-Host "  MCP endpoint: http://$Host`:$Port/mcp"
}
else {
    Write-Host "  SSE endpoint: http://$Host`:$Port/sse"
    Write-Host "  Message endpoint: http://$Host`:$Port/messages/"
}

if ($IndexAllProjects) {
    $projectNames = Get-ConfiguredProjectNames -ConfigPath $resolvedProjectsFile
    if ($projectNames.Count -eq 0) {
        throw "No projects were found in '$resolvedProjectsFile'."
    }

    Write-Host "Pre-indexing all configured projects before server startup..."
    foreach ($projectName in $projectNames) {
        Invoke-ProjectIndex -ProjectName $projectName
    }
    Write-Host "Finished pre-indexing $($projectNames.Count) project(s)."
}

& $PythonExe -m kg_rag.mcp_server --transport $Transport --host $Host --port $Port
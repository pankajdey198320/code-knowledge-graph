[CmdletBinding()]
param(
    [string]$ProjectsFile = "C:\Public\Deployment\MCP_server\KG\projects.sample.json",
    [int]$Port = 8010,
    [string]$BindHost = "127.0.0.1",
    [string]$PythonExe = "",
    [int]$RequestTimeoutSeconds = 10,
    [switch]$KeepServer
)

$ErrorActionPreference = "Stop"

function Resolve-PythonExecutable {
    if ($PythonExe) {
        return (Resolve-Path $PythonExe).Path
    }

    $localPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (Test-Path $localPython) {
        return $localPython
    }

    $python = Get-Command python -ErrorAction Stop
    return $python.Source
}

function Get-ProjectNames {
    param([string]$ConfigPath)

    $config = Get-Content -Path $ConfigPath -Raw | ConvertFrom-Json
    if (-not $config.projects) {
        throw "No projects found in '$ConfigPath'."
    }

    return @($config.projects.PSObject.Properties.Name)
}

function Wait-ForPort {
    param([string]$ComputerName, [int]$TargetPort, [int]$TimeoutSeconds)

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $connection = Test-NetConnection -ComputerName $ComputerName -Port $TargetPort -WarningAction SilentlyContinue
        if ($connection.TcpTestSucceeded) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "Server did not listen on $ComputerName`:$TargetPort within $TimeoutSeconds seconds."
}

function Test-SseEndpoint {
    param([string]$Path)

    $savedErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $headers = @(& curl.exe --silent --max-time $RequestTimeoutSeconds --output NUL --dump-header - ("http://{0}:{1}{2}" -f $BindHost, $Port, $Path) 2>$null)
    $ErrorActionPreference = $savedErrorActionPreference
    $statusLine = $headers | Select-String '^HTTP/' | Select-Object -Last 1
    $contentType = $headers | Select-String '^content-type:' | Select-Object -Last 1

    if (-not $statusLine) {
        return [PSCustomObject]@{
            Path = $Path
            Status = "NO RESPONSE"
            ContentType = ""
            Passed = $false
        }
    }

    $status = [int]($statusLine.Line -replace '^HTTP/[^ ]+\s+(\d+).*$','$1')
    return [PSCustomObject]@{
        Path = $Path
        Status = $status
        ContentType = if ($contentType) { $contentType.Line.Trim() } else { "" }
        Passed = $status -eq 200 -and $contentType.Line -match 'text/event-stream'
    }
}

$resolvedProjectsFile = (Resolve-Path $ProjectsFile).Path
$resolvedPython = Resolve-PythonExecutable
$projectNames = Get-ProjectNames -ConfigPath $resolvedProjectsFile
$startupProject = if ($projectNames -contains "Calculation") { "Calculation" } else { $projectNames[0] }
$serverProcess = $null
$stdoutLog = Join-Path ([IO.Path]::GetTempPath()) "kg-mcp-test-$Port.stdout.log"
$stderrLog = Join-Path ([IO.Path]::GetTempPath()) "kg-mcp-test-$Port.stderr.log"
$previousEnvironment = @{}

try {
    $environment = @{
        KG_PROJECTS_FILE = $resolvedProjectsFile
        ACTIVE_PROJECT = $startupProject
        KG_PRELOAD_EMBEDDINGS = "0"
        KG_USE_LOCAL_EMBEDDINGS = "1"
    }

    foreach ($name in $environment.Keys) {
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $environment[$name], "Process")
    }

    $serverProcess = Start-Process `
        -FilePath $resolvedPython `
        -ArgumentList @("-m", "kg_rag.mcp_server", "--transport", "sse", "--host", $BindHost, "--port", $Port) `
        -WorkingDirectory $PSScriptRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    Wait-ForPort -ComputerName $BindHost -TargetPort $Port -TimeoutSeconds 60

    $paths = foreach ($project in $projectNames) {
        $escapedProject = [Uri]::EscapeDataString($project)
        "/p/$escapedProject/sse"
        "/projects/$escapedProject/sse"
    }

    $results = foreach ($path in $paths) {
        $result = Test-SseEndpoint -Path $path
        $label = if ($result.Passed) { "PASS" } else { "FAIL" }
        Write-Host ("{0} {1} -> HTTP {2} {3}" -f $label, $result.Path, $result.Status, $result.ContentType)
        $result
    }

    $failed = @($results | Where-Object { -not $_.Passed })
    if ($failed.Count -gt 0) {
        throw "$($failed.Count) endpoint test(s) failed."
    }

    Write-Host "All $($results.Count) project endpoint tests passed."
}
finally {
    if ($serverProcess -and -not $KeepServer -and -not $serverProcess.HasExited) {
        $serverProcess.Kill()
        $serverProcess.WaitForExit()
    }

    if ($serverProcess) {
        $serverProcess.Dispose()
    }

    foreach ($name in $previousEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }
}

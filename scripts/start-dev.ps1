param(
    [int]$BackendPort = 18001,
    [int]$FrontendPort = 3000
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backend = $null

function Assert-PortAvailable {
    param([int]$Port, [string]$Service)

    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($listener) {
        throw "$Service port $Port is already in use. Stop that process or pass a different port."
    }
}

Assert-PortAvailable -Port $BackendPort -Service "Backend"
Assert-PortAvailable -Port $FrontendPort -Service "Frontend"

Push-Location $projectRoot
try {
    & uv sync
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency sync failed."
    }
    & uv run alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Database migration failed."
    }

    $backendLog = Join-Path $env:TEMP "jobflow-agent-backend-$BackendPort.log"
    $backendErrorLog = Join-Path $env:TEMP "jobflow-agent-backend-$BackendPort.error.log"
    $env:FRONTEND_ORIGINS = "http://localhost:$FrontendPort,http://127.0.0.1:$FrontendPort"
    $env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:$BackendPort"
    $backendOptions = @{
        FilePath = "uv"
        ArgumentList = @(
            "run", "uvicorn", "src.main:app",
            "--host", "127.0.0.1", "--port", "$BackendPort"
        )
        WorkingDirectory = $projectRoot
        RedirectStandardOutput = $backendLog
        RedirectStandardError = $backendErrorLog
        WindowStyle = "Hidden"
        PassThru = $true
    }
    $backend = Start-Process @backendOptions

    $healthUrl = "http://127.0.0.1:$BackendPort/health"
    $backendReady = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($backend.HasExited) {
            $errorTail = Get-Content $backendErrorLog -Tail 8 -ErrorAction SilentlyContinue
            throw "Backend exited during startup.`n$($errorTail -join "`n")"
        }
        try {
            Invoke-WebRequest $healthUrl -UseBasicParsing -TimeoutSec 1 | Out-Null
            $backendReady = $true
            break
        }
        catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $backendReady) {
        throw "Backend did not become healthy at $healthUrl within 10 seconds."
    }

    Write-Host "Backend: http://127.0.0.1:$BackendPort"
    Write-Host "Frontend: http://localhost:$FrontendPort"
    Write-Host "Press Ctrl+C to stop both services."

    Push-Location (Join-Path $projectRoot "frontend")
    try {
        & npm.cmd install
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend dependency install failed."
        }
        & npm.cmd run dev -- --hostname localhost --port $FrontendPort
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id
    }
    Pop-Location
}

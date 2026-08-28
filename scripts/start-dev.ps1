param(
    [int]$BackendPort = 18001,
    [int]$FrontendPort = 3000
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

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
    & uv sync --frozen
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency sync failed."
    }
    & uv run alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Database migration failed."
    }

    Push-Location (Join-Path $projectRoot "frontend")
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend dependency install failed."
        }
    }
    finally {
        Pop-Location
    }

    $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
    & $python scripts\run_dev.py `
        --backend-port $BackendPort `
        --frontend-port $FrontendPort
    if ($LASTEXITCODE -ne 0) {
        throw "Development services exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

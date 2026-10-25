param(
    [ValidateSet('Start', 'Stop', 'Status')][string]$Action = 'Status',
    [ValidateRange(1, 65535)][int]$FrontendPort = 3000
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$RuntimeDir = Join-Path $ProjectRoot 'data/local-runtime'
$StateFile = Join-Path $RuntimeDir 'services.json'
$BackendUrl = 'http://127.0.0.1:18001'
$FrontendUrl = "http://localhost:$FrontendPort"

function Get-OwnedProcess($Record) {
    $Process = Get-Process -Id $Record.pid -ErrorAction SilentlyContinue
    if ($Process -and $Process.StartTime.ToUniversalTime().Ticks.ToString() -eq $Record.started -and $Process.Path -eq $Record.executable) { return $Process }
    return $null
}
function Read-State {
    if (Test-Path -LiteralPath $StateFile) {
        $Saved = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
        foreach ($Item in $Saved) { Write-Output $Item }
    }
}
function Stop-OwnedProcess($Record) {
    $Process = Get-OwnedProcess $Record
    if ($Process) {
        # The Windows virtualenv launcher has a Python child; stop the owned tree.
        & taskkill.exe /PID $Process.Id /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not stop owned service $($Record.name)." }
        $Process.WaitForExit(5000) | Out-Null
    }
}
function Save-State($Records) {
    ConvertTo-Json -InputObject @($Records) | Set-Content -LiteralPath $StateFile -Encoding UTF8
}
function Test-Ready([string]$Url) {
    try { return (Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2).StatusCode -eq 200 } catch { return $false }
}
function Wait-Ready([string]$Url, $Process) {
    $Deadline = [DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $Deadline) {
        if ($Process.HasExited) { throw "Service exited; inspect logs in $RuntimeDir" }
        if (Test-Ready $Url) { return }
        Start-Sleep -Milliseconds 300
    }
    throw "Service did not become ready: $Url"
}

$Records = @(Read-State)
$SavedFrontend = $Records | Where-Object { $_.name -eq 'frontend' } | Select-Object -First 1
if ($SavedFrontend.url -and ($Action -ne 'Start' -or (Get-OwnedProcess $SavedFrontend))) {
    $FrontendUrl = $SavedFrontend.url
}
if ($Action -eq 'Stop') {
    foreach ($Record in $Records) {
        Stop-OwnedProcess $Record
    }
    if (Test-Path -LiteralPath $StateFile) { Remove-Item -LiteralPath $StateFile }
    Write-Output 'JobFlow local services stopped. Saved searches and schedules are preserved.'
    exit 0
}
if ($Action -eq 'Status') {
    foreach ($Record in $Records) { Write-Output "$($Record.name): $([bool](Get-OwnedProcess $Record))" }
    Write-Output "Backend ready: $(Test-Ready ($BackendUrl + '/health'))"
    Write-Output "Frontend ready: $(Test-Ready $FrontendUrl)"
    if (Test-Ready ($BackendUrl + '/health')) {
        $Snapshot = Invoke-RestMethod -Uri "$BackendUrl/api/tracking/summary" -Headers @{'X-User-ID'='local-user'}
        Write-Output "Scheduler running: $($Snapshot.scheduler_running)"
        foreach ($Search in $Snapshot.searches) { Write-Output "$($Search.goal.id): every $($Search.goal.update_interval_minutes) minutes; next $($Search.goal.next_update_at)" }
    }
    exit 0
}

$Running = @($Records | Where-Object { Get-OwnedProcess $_ })
if ($Running.Count) {
    if ($Running.Count -eq 2 -and (Test-Ready ($BackendUrl + '/health')) -and (Test-Ready $FrontendUrl)) {
        Write-Output "JobFlow is already running: $FrontendUrl"
        exit 0
    }
    throw 'A previous managed service is still running. Run -Action Stop, then Start.'
}
if ($FrontendPort -eq 18001) { throw 'FrontendPort must differ from backend port 18001.' }
foreach ($Port in @(18001, $FrontendPort)) {
    $Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try { $Listener.Start() } catch {
        throw "Cannot bind port ${Port}: $($_.Exception.InnerException.Message) For the frontend, select another -FrontendPort. No existing service was stopped."
    } finally { $Listener.Stop() }
}
$PythonPath = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
$FrontendRoot = Join-Path $ProjectRoot 'frontend'
$BuildId = Join-Path $FrontendRoot '.next-tracking-build/BUILD_ID'
if (-not (Test-Path -LiteralPath $BuildId)) { throw 'Build frontend first with NEXT_DIST_DIR=.next-tracking-build and NEXT_PUBLIC_API_URL=http://127.0.0.1:18001.' }
$NodePath = (Get-Command node -ErrorAction Stop).Source
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
$Names = @('FRONTEND_ORIGINS', 'NEXT_DIST_DIR')
$Previous = @{}
foreach ($Name in $Names) { $Previous[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process') }
$Started = @()
try {
    $env:FRONTEND_ORIGINS = "http://localhost:$FrontendPort,http://127.0.0.1:$FrontendPort"
    $env:NEXT_DIST_DIR = '.next-tracking-build'
    $Backend = Start-Process -FilePath $PythonPath -ArgumentList '-m uvicorn src.main:app --host 127.0.0.1 --port 18001' -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $RuntimeDir 'backend.log') -RedirectStandardError (Join-Path $RuntimeDir 'backend.error.log')
    $Started += @{name='backend'; pid=$Backend.Id; started=$Backend.StartTime.ToUniversalTime().Ticks.ToString(); executable=$PythonPath}
    Save-State $Started
    Wait-Ready ($BackendUrl + '/health') $Backend
    $Frontend = Start-Process -FilePath $NodePath -ArgumentList "node_modules/next/dist/bin/next start --hostname localhost --port $FrontendPort" -WorkingDirectory $FrontendRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $RuntimeDir 'frontend.log') -RedirectStandardError (Join-Path $RuntimeDir 'frontend.error.log')
    $Started += @{name='frontend'; pid=$Frontend.Id; started=$Frontend.StartTime.ToUniversalTime().Ticks.ToString(); executable=$NodePath; url=$FrontendUrl}
    Save-State $Started
    Wait-Ready $FrontendUrl $Frontend
    Write-Output "JobFlow running: $FrontendUrl"
    Write-Output "Logs: $RuntimeDir"
} catch {
    foreach ($Record in $Started) { Stop-OwnedProcess $Record }
    if (Test-Path -LiteralPath $StateFile) { Remove-Item -LiteralPath $StateFile }
    throw
} finally {
    foreach ($Name in $Names) { [Environment]::SetEnvironmentVariable($Name, $Previous[$Name], 'Process') }
}

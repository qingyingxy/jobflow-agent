param()

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontendRoot = Join-Path $projectRoot "frontend"
$assetsRoot = Join-Path $projectRoot "docs\assets"
$previousCaptureFlag = $env:UPDATE_DEMO_ASSETS

New-Item -ItemType Directory -Force -Path $assetsRoot | Out-Null
$env:UPDATE_DEMO_ASSETS = "1"

try {
    Push-Location $frontendRoot
    try {
        & npm.cmd run demo:capture
        if ($LASTEXITCODE -ne 0) {
            throw "Playwright demo capture failed."
        }

    }
    finally {
        Pop-Location
    }

    $gifOutput = Join-Path $assetsRoot "jobflow-discovery-demo.gif"
    $frameRoot = Join-Path $frontendRoot "test-results"
    & uv run --with pillow python (Join-Path $projectRoot "scripts\build-demo-gif.py") `
        --frame (Join-Path $frameRoot "demo-01-search.png") `
        --frame (Join-Path $frameRoot "demo-02-strict.png") `
        --frame (Join-Path $frameRoot "demo-03-expanded.png") `
        --output $gifOutput
    if ($LASTEXITCODE -ne 0) {
        throw "GIF conversion failed."
    }

    Write-Host "Screenshot: $(Join-Path $assetsRoot 'jobflow-discovery-demo.png')"
    Write-Host "GIF: $gifOutput"
}
finally {
    if ($null -eq $previousCaptureFlag) {
        Remove-Item Env:UPDATE_DEMO_ASSETS -ErrorAction SilentlyContinue
    }
    else {
        $env:UPDATE_DEMO_ASSETS = $previousCaptureFlag
    }
}

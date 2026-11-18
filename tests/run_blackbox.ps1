# Reset DB, ingest golden batches, start the API, run the blackbox suite in stages.
# GOLDEN LOAD ORDER (data/synthetic/golden_cases): batch_1 -> batch_2 -> batch_bad -> batch_3 (-> late: batch_4_revision, batch_overlap, batch_allbad).
#   The late stage (pytest -m late) ingests batch_4_revision, batch_overlap and batch_allbad itself, in that order (S17, #6, S11b: all rows bad => rejected, exit 1).
#   batch_bad (verdant orders file with 2 of 5 rows missing order_id: those rows are left out, the file loads, exit 0) is first loaded by the S11 test in stage 2
#   and re-asserted explicitly before batch_3 below. Tests marked `golden_bad` (verdant projection unavailable, health failure
#   counts) are valid only after batch_bad and are never run against data without it (e.g. the full synthetic set: add
#   `-m "not golden_bad"` there).
# Usage (repo root, PowerShell):  .\tests\run_blackbox.ps1 [-Python python] [-Port 8000]
param(
    [string]$Python = "python",
    [int]$Port = 8000,
    [switch]$Ui,        # also run the Playwright UI tests (frontend on :3000)
    [switch]$Perf,      # also run the latency budget (load the FULL synthetic data first)
    [string]$DatabaseUrl = $(if ($env:DATABASE_URL) { $env:DATABASE_URL } else { "postgresql://darkroom:darkroom@localhost:5432/darkroom" })
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Repo "backend"
$Golden = Join-Path $Repo "data\synthetic\golden_cases"
$env:DATABASE_URL = $DatabaseUrl
$env:BASE_URL = "http://localhost:$Port"
$env:BACKEND_PYTHON = $Python
$env:BACKEND_DIR = $Backend
if (-not $env:AUTH_SECRET) { $env:AUTH_SECRET = "blackbox-test-secret" }
if (-not $env:CORS_ORIGINS) { $env:CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000" }

function Invoke-Cli($cliArgs) {
    Push-Location $Backend
    try { & $Python -m app.cli @cliArgs; return $LASTEXITCODE } finally { Pop-Location }
}

Write-Host "== regenerate fixtures (deterministic) =="
& $Python (Join-Path $Repo "scripts\generate_synthetic_data.py") | Out-Null

Write-Host "== reset DB (drop bronze/silver/gold/meta) and migrate =="
$sql = "DROP SCHEMA IF EXISTS gold CASCADE; DROP SCHEMA IF EXISTS silver CASCADE; DROP SCHEMA IF EXISTS bronze CASCADE; DROP SCHEMA IF EXISTS meta CASCADE;"
if (Get-Command psql -ErrorAction SilentlyContinue) { psql $DatabaseUrl -v ON_ERROR_STOP=1 -c $sql } else {
    & $Python -c "import psycopg,sys; c=psycopg.connect(sys.argv[1], autocommit=True); c.execute(sys.argv[2])" $DatabaseUrl $sql
}
if ($LASTEXITCODE -ne 0) { throw "DB reset failed" }
if ((Invoke-Cli @("migrate")) -ne 0) { throw "migrate failed" }

Write-Host "== ingest golden batch_1 =="
if ((Invoke-Cli @("ingest", (Join-Path $Golden "batch_1"))) -ne 0) { throw "golden batch_1 ingest failed" }

Write-Host "== start API on port $Port =="
$api = Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "app.main:app", "--port", "$Port") `
    -WorkingDirectory $Backend -PassThru -WindowStyle Hidden
try {
    $up = $false
    for ($i = 0; $i -lt 40; $i++) {
        try { Invoke-RestMethod "http://localhost:$Port/healthz" | Out-Null; $up = $true; break } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $up) { throw "API did not come up" }

    Push-Location (Join-Path $Repo "tests")
    Write-Host "== stage 1: after batch_1 only =="
    & $Python -m pytest blackbox -m "not after_b2 and not after_b3 and not v2 and not perf and not late and not ui" -q
    $s1 = $LASTEXITCODE

    Write-Host "== ingest golden batch_2 =="
    if ((Invoke-Cli @("ingest", (Join-Path $Golden "batch_2"))) -ne 0) { throw "golden batch_2 ingest failed" }

    Write-Host "== stage 2: after batch_1 + batch_2 =="
    & $Python -m pytest blackbox -m "not b1_only and not after_b3 and not v2 and not perf and not late and not ui" -q
    $s2 = $LASTEXITCODE

    Write-Host "== ensure golden batch_bad is loaded (replay is a no-op; exit 0: its bad rows are only left out) =="
    Invoke-Cli @("ingest", (Join-Path $Golden "batch_bad")) | Out-Null

    Write-Host "== ingest golden batch_3 (amendment 2: September data, new creators) =="
    if ((Invoke-Cli @("ingest", (Join-Path $Golden "batch_3"))) -ne 0) { throw "golden batch_3 ingest failed" }

    Write-Host "== stage 3: amendment-2 tests (essential #3 #4 #5 #6 #10 #12, S13-S18) =="
    & $Python -m pytest blackbox -m "(after_b3 or v2) and not late and not perf and not ui and not synth" -q
    $s3 = $LASTEXITCODE

    Write-Host "== stage 4: late mutating tests (ETag change on new revision, overlapping weekly resend) =="
    & $Python -m pytest blackbox -m "late" -q
    $s4 = $LASTEXITCODE

    $s5 = 0
    if ($Ui) { Write-Host "== stage 5: UI (S20) =="; & $Python -m pytest blackbox -m "ui" -q; $s5 = $LASTEXITCODE }
    $s6 = 0
    if ($Perf) { Write-Host "== stage 6: latency budget (S19) =="; & $Python -m pytest blackbox -m "perf" -q; $s6 = $LASTEXITCODE }
    Pop-Location
    exit [int](($s1 -ne 0) -or ($s2 -ne 0) -or ($s3 -ne 0) -or ($s4 -ne 0) -or ($s5 -ne 0) -or ($s6 -ne 0))
}
finally {
    if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force }
}

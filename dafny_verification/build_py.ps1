# Build pipeline for the Dafny formal verification module (Windows).
#
#   1. Verifies every .dfy source and appends the solver output to
#      docs\verification_report.txt.
#   2. Compiles RiskGateway.dfy (the entry module) into a Python package under
#      risk_control\_generated\verified_risk-py\ that the engine imports.
#
# Requirements: Dafny >= 4.x on PATH (or set $env:DAFNY to the executable).
$ErrorActionPreference = "Stop"

$DAFNY = if ($env:DAFNY) { $env:DAFNY } else { "dafny" }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SrcDir = Join-Path $ScriptDir "src"
$ProjectRoot = Split-Path -Parent $ScriptDir
$OutDir = Join-Path $ProjectRoot "risk_control\_generated"
$DocsDir = Join-Path $ProjectRoot "docs"
$Report = Join-Path $DocsDir "verification_report.txt"

New-Item -ItemType Directory -Force -Path $OutDir, $DocsDir | Out-Null

Write-Host "==> Verifying Dafny sources"
$reportLines = @()
Get-ChildItem -LiteralPath $SrcDir -Filter "*.dfy" | ForEach-Object {
    Write-Host "  -> $($_.Name)"
    $output = & $DAFNY verify $_.FullName --verification-time-limit 30 2>&1
    $reportLines += $output
    Write-Output $output
    if ($LASTEXITCODE -ne 0) { throw "Dafny verification failed for $($_.Name)" }
}
$reportLines | Out-File -LiteralPath $Report -Encoding utf8

Write-Host "==> Compiling RiskGateway.dfy to Python"
$OutputBase = Join-Path $OutDir "verified_risk"
& $DAFNY translate py (Join-Path $SrcDir "RiskGateway.dfy") --output:$OutputBase --include-runtime
if ($LASTEXITCODE -ne 0) { throw "Dafny translation failed" }

Write-Host "==> Done. Generated Python package: $(Join-Path $OutDir 'verified_risk-py')"

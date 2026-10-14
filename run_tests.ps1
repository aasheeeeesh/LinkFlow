# Run every Linkflow Lab test: backend (pytest), frontend type check (tsc) and frontend tests (vitest).
$env:PYTHONIOENCODING = "utf-8"
Write-Host "`n=== Backend tests (pytest) ===" -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m pytest backend/tests -o addopts="" -v --no-header -p no:cacheprovider
$backend = $LASTEXITCODE
Push-Location frontend
Write-Host "`n=== Frontend type check (tsc) ===" -ForegroundColor Cyan
npx tsc -b
$tsc = $LASTEXITCODE
if ($tsc -eq 0) { Write-Host "Type check clean" -ForegroundColor Green }
Write-Host "`n=== Frontend tests (vitest) ===" -ForegroundColor Cyan
npx vitest run
$vitest = $LASTEXITCODE
Pop-Location
Write-Host "`n=== Summary ===" -ForegroundColor Cyan
foreach ($r in @(@("Backend pytest", $backend), @("Frontend tsc", $tsc), @("Frontend vitest", $vitest))) {
    if ($r[1] -eq 0) { Write-Host ("PASS  " + $r[0]) -ForegroundColor Green } else { Write-Host ("FAIL  " + $r[0]) -ForegroundColor Red }
}

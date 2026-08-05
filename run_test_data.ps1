#!/usr/bin/env powershell
<#
.SYNOPSIS
Run test data population for SmartHandoff localhost
#>

Write-Host "`n" + ("="*80) -ForegroundColor Cyan
Write-Host "📝 SmartHandoff Test Data Population" -ForegroundColor Cyan
Write-Host ("="*80) -ForegroundColor Cyan

# Set environment variables
Write-Host "`n[SETUP] Setting environment variables..." -ForegroundColor Yellow
$env:PYTHONPATH = "."
$env:PRIMARY_DATABASE_URL = "postgresql+asyncpg://postgres:SmartHandoff@123@127.0.0.1:9432/smarthandoff"
$env:REPLICA_DATABASE_URL = "postgresql+asyncpg://postgres:SmartHandoff@123@127.0.0.1:9432/smarthandoff"
$env:PHI_ENCRYPTION_KEY = "peF3ahNpMuTZD6tm-B9tNA5YKZlxYSQNYVZd2x6Ou3A="
$env:ALLOW_UNAUTHENTICATED_LOCALHOST = "true"
$env:FHIR_BASE_URL = "https://r4.smarthealthit.org"

Write-Host "✅ Environment variables set" -ForegroundColor Green

# Check if we're in the right directory
if (-not (Test-Path "backend\populate_test_data.py")) {
    Write-Host "❌ Error: backend/populate_test_data.py not found" -ForegroundColor Red
    Write-Host "Please run this script from the SmartHandoff root directory" -ForegroundColor Yellow
    exit 1
}

# Run the test data population script
Write-Host "`n[RUN] Executing population script..." -ForegroundColor Yellow
Write-Host "-" * 80

cd backend
python populate_test_data.py
$exitCode = $LASTEXITCODE
cd ..

Write-Host "-" * 80

if ($exitCode -eq 0) {
    Write-Host "`n✅ Test data population completed successfully!" -ForegroundColor Green
    Write-Host "`n📝 You can now:" -ForegroundColor Cyan
    Write-Host "  • Query the database with test data" -ForegroundColor Gray
    Write-Host "  • Start the backend server" -ForegroundColor Gray
    Write-Host "  • Test API endpoints" -ForegroundColor Gray
} else {
    Write-Host "`n❌ Test data population failed with exit code: $exitCode" -ForegroundColor Red
    exit $exitCode
}

Write-Host "`n" + ("="*80) -ForegroundColor Green

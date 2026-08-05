#!/usr/bin/env powershell
<#
.SYNOPSIS
Quick setup script to configure environment for SmartHandoff localhost development
.DESCRIPTION
Sets all necessary environment variables for connecting to Cloud SQL proxy and running the backend
.USAGE
# Option 1: Run directly
.\setup_env.ps1

# Option 2: Source it to load variables into current session
. .\setup_env.ps1

# Then start the backend:
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
#>

Write-Host "`n" + ("="*80) -ForegroundColor Cyan
Write-Host "⚙️  SmartHandoff Localhost Environment Setup" -ForegroundColor Cyan
Write-Host ("="*80) -ForegroundColor Cyan

# Check if Cloud SQL proxy is running
Write-Host "`n[1/2] Checking Cloud SQL Proxy..." -ForegroundColor Yellow
$proxyCheck = Get-NetTCPConnection -LocalPort 9432 -ErrorAction SilentlyContinue
if ($proxyCheck) {
    Write-Host "✅ Cloud SQL Proxy is running on port 9432" -ForegroundColor Green
} else {
    Write-Host "⚠️  Cloud SQL Proxy is NOT running on port 9432" -ForegroundColor Yellow
    Write-Host "    Start it with: cloud_sql_proxy -instances=smarthandoff:us-central1:smarthandoff=tcp:9432" -ForegroundColor Gray
}

# Set environment variables
Write-Host "`n[2/2] Setting environment variables..." -ForegroundColor Yellow

Write-Host "   Setting PYTHONPATH..." -ForegroundColor Gray
$env:PYTHONPATH = "backend"

Write-Host "   Setting DATABASE URLs..." -ForegroundColor Gray
$env:PRIMARY_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
$env:REPLICA_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"

Write-Host "   Setting encryption key..." -ForegroundColor Gray
$env:PHI_ENCRYPTION_KEY = "peF3ahNpMuTZD6tm-B9tNA5YKZlxYSQNYVZd2x6Ou3A="

Write-Host "   Setting FHIR and auth settings..." -ForegroundColor Gray
$env:ALLOW_UNAUTHENTICATED_LOCALHOST = "true"
$env:FHIR_BASE_URL = "https://r4.smarthealthit.org"

Write-Host "`n✅ Environment variables set successfully!" -ForegroundColor Green

Write-Host "`n📋 Environment Configuration:" -ForegroundColor Cyan
Write-Host "   PYTHONPATH:                    $env:PYTHONPATH" -ForegroundColor Gray
Write-Host "   PRIMARY_DATABASE_URL:          localhost:9432" -ForegroundColor Gray
Write-Host "   REPLICA_DATABASE_URL:          localhost:9432" -ForegroundColor Gray
Write-Host "   PHI_ENCRYPTION_KEY:            [configured]" -ForegroundColor Gray
Write-Host "   ALLOW_UNAUTHENTICATED_LOCALHOST: $env:ALLOW_UNAUTHENTICATED_LOCALHOST" -ForegroundColor Gray
Write-Host "   FHIR_BASE_URL:                 $env:FHIR_BASE_URL" -ForegroundColor Gray

Write-Host "`n" + ("="*80) -ForegroundColor Green
Write-Host "🚀 Ready to start backend server!" -ForegroundColor Green
Write-Host ("="*80) -ForegroundColor Green

Write-Host "`n💡 To start the backend server, run:" -ForegroundColor Cyan
Write-Host "   cd backend" -ForegroundColor Gray
Write-Host "   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload" -ForegroundColor Gray

Write-Host "`n💡 Then test with:" -ForegroundColor Cyan
Write-Host "   curl http://localhost:8000/api/v1/patients" -ForegroundColor Gray
Write-Host "   curl http://localhost:8000/docs  # API documentation" -ForegroundColor Gray

Write-Host "`n"

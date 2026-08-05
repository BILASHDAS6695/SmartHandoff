#!/usr/bin/env powershell
# Setup environment variables for SmartHandoff localhost

# Check if Cloud SQL proxy is running
$proxyCheck = Get-NetTCPConnection -LocalPort 9432 -ErrorAction SilentlyContinue
if ($proxyCheck) {
    Write-Host "Cloud SQL Proxy is running on port 9432" -ForegroundColor Green
} else {
    Write-Host "WARNING: Cloud SQL Proxy is NOT running on port 9432" -ForegroundColor Yellow
}

# Set environment variables
$env:PYTHONPATH = "backend"
$env:PRIMARY_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
$env:REPLICA_DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
$env:PHI_ENCRYPTION_KEY = "peF3ahNpMuTZD6tm-B9tNA5YKZlxYSQNYVZd2x6Ou3A="
$env:ALLOW_UNAUTHENTICATED_LOCALHOST = "true"
$env:FHIR_BASE_URL = "https://r4.smarthealthit.org"

Write-Host "Environment variables configured!" -ForegroundColor Green

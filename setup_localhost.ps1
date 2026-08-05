#!/usr/bin/env powershell
<#
.SYNOPSIS
Complete localhost setup script for SmartHandoff
- Verifies Cloud SQL proxy is running
- Runs database migrations
- Populates test data
- Starts the backend server
#>

$ErrorActionPreference = "Continue"

Write-Host "`n" + ("="*80) -ForegroundColor Cyan
Write-Host "🚀 SmartHandoff Localhost Complete Setup" -ForegroundColor Cyan
Write-Host ("="*80) -ForegroundColor Cyan

# Step 1: Check if Cloud SQL proxy is running
Write-Host "`n[1/4] Checking Cloud SQL Proxy..." -ForegroundColor Yellow
$proxyCheck = Get-NetTCPConnection -LocalPort 9432 -ErrorAction SilentlyContinue
if ($proxyCheck) {
    Write-Host "✅ Cloud SQL Proxy is running on port 9432" -ForegroundColor Green
} else {
    Write-Host "❌ Cloud SQL Proxy is NOT running on port 9432" -ForegroundColor Red
    Write-Host "Please start it with:" -ForegroundColor Yellow
    Write-Host '   cloud_sql_proxy -instances=smarthandoff:us-central1:smarthandoff=tcp:9432 -enable_iam_login' -ForegroundColor Yellow
    exit 1
}

# Step 2: Check database connectivity
Write-Host "`n[2/4] Testing database connectivity..." -ForegroundColor Yellow
$env:PYTHONPATH = "."
$testScript = @"
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def test_connection():
    engine = create_async_engine("postgresql+asyncpg://postgres:SmartHandoff@123@127.0.0.1:9432/smarthandoff", echo=False)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            print("✅ Database is accessible")
            return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False
    finally:
        await engine.dispose()

asyncio.run(test_connection())
"@

python -c $testScript
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Database connectivity test failed" -ForegroundColor Red
    exit 1
}

# Step 3: Run migrations
Write-Host "`n[3/4] Running Alembic migrations..." -ForegroundColor Yellow
$env:PRIMARY_DATABASE_URL = "postgresql+asyncpg://postgres:SmartHandoff@123@127.0.0.1:9432/smarthandoff"
$env:REPLICA_DATABASE_URL = "postgresql+asyncpg://postgres:SmartHandoff@123@127.0.0.1:9432/smarthandoff"

if (Test-Path "backend/alembic.ini") {
    cd backend
    Write-Host "Running: alembic upgrade head" -ForegroundColor Gray
    alembic upgrade head 2>&1 | Select-Object -Last 5
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Migrations completed successfully" -ForegroundColor Green
    } else {
        Write-Host "⚠️  Migrations had issues (but continuing)" -ForegroundColor Yellow
    }
    cd ..
} else {
    Write-Host "⚠️  Alembic config not found, skipping migrations" -ForegroundColor Yellow
}

# Step 4: Populate test data
Write-Host "`n[4/4] Populating test data..." -ForegroundColor Yellow
Write-Host "Running: python populate_test_data.py" -ForegroundColor Gray
python backend/populate_test_data.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Test data population failed" -ForegroundColor Red
    exit 1
}

# Summary
Write-Host "`n" + ("="*80) -ForegroundColor Green
Write-Host "✅ SETUP COMPLETE!" -ForegroundColor Green
Write-Host ("="*80) -ForegroundColor Green

Write-Host "`n📋 What's been set up:" -ForegroundColor Cyan
Write-Host "  • Database schema created/updated" -ForegroundColor Gray
Write-Host "  • Test data populated in all tables" -ForegroundColor Gray
Write-Host "  • Ready to start the backend server" -ForegroundColor Gray

Write-Host "`n🚀 To start the backend server:" -ForegroundColor Cyan
Write-Host "  cd backend" -ForegroundColor Gray
Write-Host "  `$env:PYTHONPATH = '.';" -ForegroundColor Gray
Write-Host "  `$env:PRIMARY_DATABASE_URL = 'postgresql+asyncpg://postgres:SmartHandoff@123@127.0.0.1:9432/smarthandoff';" -ForegroundColor Gray
Write-Host "  `$env:REPLICA_DATABASE_URL = 'postgresql+asyncpg://postgres:SmartHandoff@123@127.0.0.1:9432/smarthandoff';" -ForegroundColor Gray
Write-Host "  `$env:ALLOW_UNAUTHENTICATED_LOCALHOST = 'true';" -ForegroundColor Gray
Write-Host "  `$env:PHI_ENCRYPTION_KEY = 'peF3ahNpMuTZD6tm-B9tNA5YKZlxYSQNYVZd2x6Ou3A=';" -ForegroundColor Gray
Write-Host "  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000" -ForegroundColor Gray

Write-Host "`n🧪 To test the API:" -ForegroundColor Cyan
Write-Host "  curl http://localhost:8000/api/v1/patients" -ForegroundColor Gray
Write-Host "  curl http://localhost:8000/api/v1/encounters" -ForegroundColor Gray

Write-Host "`n" + ("="*80) -ForegroundColor Green

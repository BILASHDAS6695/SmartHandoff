# Deploy SmartHandoff Backend to Google Cloud Run
# Usage: .\deploy-backend.ps1

param(
    [string]$ProjectId = "smarthandoff",
    [string]$Region = "us-central1",
    [string]$ServiceName = "smarthandoff-backend",
    [string]$DatabaseInstance = "smarthandoff:us-central1:smarthandoff"
)

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Deploying SmartHandoff Backend to Cloud Run" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Project ID: $ProjectId"
Write-Host "  Region: $Region"
Write-Host "  Service Name: $ServiceName"
Write-Host "  Database: $DatabaseInstance"
Write-Host ""

# Navigate to backend directory
Set-Location "$env:USERPROFILE\source\repos\SmartHandoff\backend"

Write-Host "Step 1: Building and deploying backend service..." -ForegroundColor Green
Write-Host ""

# Deploy to Cloud Run
gcloud run deploy $ServiceName `
    --source . `
    --project=$ProjectId `
    --region=$Region `
    --platform=managed `
    --allow-unauthenticated `
    --min-instances=1 `
    --max-instances=10 `
    --memory=1Gi `
    --cpu=2 `
    --timeout=300 `
    --port=8080 `
    --add-cloudsql-instances=$DatabaseInstance `
    --set-env-vars="DATABASE_URL=postgresql+asyncpg://postgres:SmartHandoff%40123@/smarthandoff?host=/cloudsql/$DatabaseInstance,CORS_ORIGINS=https://smarthandoff-frontend-52528248131.us-central1.run.app"

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host "Backend Deployment Successful!" -ForegroundColor Green
    Write-Host "========================================`n" -ForegroundColor Green
    
    Write-Host "Service URL:" -ForegroundColor Yellow
    gcloud run services describe $ServiceName --region=$Region --project=$ProjectId --format="value(status.url)"
    
    Write-Host "`nNext Steps:" -ForegroundColor Yellow
    Write-Host "1. Update frontend environment with backend URL"
    Write-Host "2. Configure CORS if needed"
    Write-Host "3. Set up custom domain (optional)"
    Write-Host "4. Configure authentication secrets"
    Write-Host ""
} else {
    Write-Host "`nDeployment failed. Check logs above." -ForegroundColor Red
}

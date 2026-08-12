# Deploy SmartHandoff Frontend to Google Cloud Run
# Usage: .\deploy-frontend.ps1

param(
    [string]$ProjectId = "smarthandoff",
    [string]$Region = "us-central1",
    [string]$ServiceName = "smarthandoff-frontend",
    [string]$BackendUrl = ""
)

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Deploying SmartHandoff Frontend to Cloud Run" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Project ID: $ProjectId"
Write-Host "  Region: $Region"
Write-Host "  Service Name: $ServiceName"
if ($BackendUrl) {
    Write-Host "  Backend URL: $BackendUrl"
}
Write-Host ""

# Navigate to frontend directory relative to this script's location
Set-Location ([System.IO.Path]::Combine($PSScriptRoot, "..", "frontend"))

Write-Host "Step 1: Building and deploying frontend..." -ForegroundColor Green
Write-Host ""

# Prepare environment variables
$envVars = @()
if ($BackendUrl) {
    $envVars += "API_BASE_URL=$BackendUrl"
}

# Deploy to Cloud Run
if ($envVars.Count -gt 0) {
    gcloud run deploy $ServiceName `
        --source . `
        --project=$ProjectId `
        --region=$Region `
        --platform=managed `
        --allow-unauthenticated `
        --min-instances=1 `
        --max-instances=5 `
        --memory=512Mi `
        --cpu=1 `
        --timeout=60 `
        --port=8080 `
        --set-env-vars=($envVars -join ',')
} else {
    gcloud run deploy $ServiceName `
        --source . `
        --project=$ProjectId `
        --region=$Region `
        --platform=managed `
        --allow-unauthenticated `
        --min-instances=1 `
        --max-instances=5 `
        --memory=512Mi `
        --cpu=1 `
        --timeout=60 `
        --port=8080
}

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host "Frontend Deployment Successful!" -ForegroundColor Green
    Write-Host "========================================`n" -ForegroundColor Green
    
    Write-Host "Frontend URL:" -ForegroundColor Yellow
    $frontendUrl = gcloud run services describe $ServiceName --region=$Region --project=$ProjectId --format="value(status.url)"
    Write-Host $frontendUrl
    
    Write-Host "`nNext Steps:" -ForegroundColor Yellow
    Write-Host "1. Test the application at: $frontendUrl"
    Write-Host "2. Configure custom domain (optional)"
    Write-Host "3. Set up Cloud CDN for better performance (optional)"
    Write-Host "4. Update backend CORS to allow frontend origin"
    Write-Host ""
} else {
    Write-Host "`nDeployment failed. Check logs above." -ForegroundColor Red
}

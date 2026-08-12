# Deploy SmartHandoff Backend to Google Cloud Run
# Usage: .\deploy-backend.ps1
#
# Required environment variables (set before running):
#   GOOGLE_OAUTH_CLIENT_ID     - Google OAuth client ID
#   GOOGLE_OAUTH_CLIENT_SECRET - Google OAuth client secret
#   DB_PASSWORD                - Cloud SQL postgres password
#   PHI_ENCRYPTION_KEY         - Base64-encoded PHI encryption key
#   JWT_SIGNING_KEY            - Minimum 32-character HS256 signing key
#   AZURE_SIGNALR_CONNECTION_STRING - Azure SignalR connection string
#
# Optional environment variables:
#   CORS_ORIGINS               - Comma-separated allowed CORS origins
#   FHIR_BASE_URL              - FHIR server base URL

param(
    [string]$ProjectId = "smarthandoff",
    [string]$Region = "us-central1",
    [string]$ServiceName = "smarthandoff-backend",
    [string]$DatabaseInstance = "smarthandoff:us-central1:smarthandoff",
    [string]$CorsOrigins = "https://smarthandoff-frontend-h67r7fyswq-uc.a.run.app,https://smarthandoff-frontend-52528248131.us-central1.run.app",
    [string]$FhirBaseUrl = "https://r4.smarthealthit.org"
)

$requiredSecrets = @(
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "DB_PASSWORD",
    "PHI_ENCRYPTION_KEY",
    "JWT_SIGNING_KEY",
    "AZURE_SIGNALR_CONNECTION_STRING"
)

$missing = $requiredSecrets | Where-Object { -not [Environment]::GetEnvironmentVariable($_) }
if ($missing) {
    Write-Host "ERROR: The following required environment variables are not set:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host "`nSet them before running this script, for example:" -ForegroundColor Yellow
    Write-Host '  $env:GOOGLE_OAUTH_CLIENT_ID = "your-client-id"' -ForegroundColor Yellow
    exit 1
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Deploying SmartHandoff Backend to Cloud Run" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Project ID: $ProjectId"
Write-Host "  Region: $Region"
Write-Host "  Service Name: $ServiceName"
Write-Host "  Database: $DatabaseInstance"
Write-Host ""

# Navigate to backend directory relative to this script's location
Set-Location ([System.IO.Path]::Combine($PSScriptRoot, "..", "backend"))

Write-Host "Step 1: Building and deploying backend service..." -ForegroundColor Green
Write-Host ""

# Build the Cloud SQL Unix socket path and common connection string pieces
$socketDir = "/cloudsql/$DatabaseInstance"
$dbPassword = [Environment]::GetEnvironmentVariable("DB_PASSWORD")
# URL-encode special characters (@, :, /, etc.) so the password does not break the URL parser.
$encodedDbPassword = [System.Uri]::EscapeDataString($dbPassword)
$dbUrl = "postgresql+asyncpg://postgres:${encodedDbPassword}@/smarthandoff?host=$socketDir"

# Write environment variables to a YAML file to avoid comma escaping issues.
# NOTE: For production, mount these from Google Secret Manager instead of local env vars.
$envVarsPath = Join-Path $env:TEMP "backend-env-vars.yaml"
@"
PRIMARY_DATABASE_URL: '$dbUrl'
REPLICA_DATABASE_URL: '$dbUrl'
PHI_ENCRYPTION_KEY: '$([Environment]::GetEnvironmentVariable("PHI_ENCRYPTION_KEY"))'
JWT_SIGNING_KEY: '$([Environment]::GetEnvironmentVariable("JWT_SIGNING_KEY"))'
AZURE_SIGNALR_CONNECTION_STRING: '$([Environment]::GetEnvironmentVariable("AZURE_SIGNALR_CONNECTION_STRING"))'
CORS_ORIGINS: '$CorsOrigins'
ALLOW_UNAUTHENTICATED_LOCALHOST: 'false'
FHIR_BASE_URL: '$FhirBaseUrl'
OIDC_CLIENT_ID: '$([Environment]::GetEnvironmentVariable("GOOGLE_OAUTH_CLIENT_ID"))'
GOOGLE_OAUTH_CLIENT_ID: '$([Environment]::GetEnvironmentVariable("GOOGLE_OAUTH_CLIENT_ID"))'
OAUTH_CLIENT_SECRET: '$([Environment]::GetEnvironmentVariable("GOOGLE_OAUTH_CLIENT_SECRET"))'
GOOGLE_OAUTH_CLIENT_SECRET: '$([Environment]::GetEnvironmentVariable("GOOGLE_OAUTH_CLIENT_SECRET"))'
"@ | Set-Content -Path $envVarsPath -Encoding UTF8

Write-Host "Using env vars file: $envVarsPath" -ForegroundColor Gray

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
    --env-vars-file=$envVarsPath

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

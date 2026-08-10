#!/bin/bash
# Deploy notification-service to Cloud Run
# Usage: ./deploy.sh [environment] [region]

set -euo pipefail

# Configuration
ENVIRONMENT="${1:-dev}"
REGION="${2:-us-central1}"
SERVICE_NAME="notification-service"

# Load project ID from gcloud config
PROJECT_ID=$(gcloud config get-value project)

if [ -z "$PROJECT_ID" ]; then
    echo "ERROR: GCP project not set. Run: gcloud config set project YOUR_PROJECT_ID"
    exit 1
fi

echo "========================================="
echo "Deploying notification-service"
echo "========================================="
echo "Environment: $ENVIRONMENT"
echo "Region: $REGION"
echo "Project: $PROJECT_ID"
echo "========================================="

# Build container image
echo "Building container image..."
gcloud builds submit \
    --project="$PROJECT_ID" \
    --config=cloudbuild.yaml \
    --substitutions="_ENVIRONMENT=$ENVIRONMENT,_REGION=$REGION,_SERVICE_NAME=notification-svc"

# Get the image URL
IMAGE_URL="${REGION}-docker.pkg.dev/${PROJECT_ID}/smarthandoff-${ENVIRONMENT}/notification-svc:latest"

echo "Image built: $IMAGE_URL"

# Deploy to Cloud Run
echo "Deploying to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --image="$IMAGE_URL" \
    --platform=managed \
    --allow-unauthenticated \
    --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,PUBSUB_SUBSCRIPTION_ID=notification-service-sub" \
    --set-secrets="DATABASE_URL=database-url:latest,SENDGRID_FROM_EMAIL=sendgrid-from-email:latest,TWILIO_FROM_NUMBER=twilio-phone-number:latest" \
    --min-instances=1 \
    --max-instances=10 \
    --memory=512Mi \
    --cpu=1 \
    --timeout=300 \
    --concurrency=80 \
    --max-instances=10 \
    --service-account="notification-service@${PROJECT_ID}.iam.gserviceaccount.com"

# Get service URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --format='value(status.url)')

echo "========================================="
echo "Deployment complete!"
echo "========================================="
echo "Service URL: $SERVICE_URL"
echo ""
echo "Next steps:"
echo "1. Test health endpoint:"
echo "   curl $SERVICE_URL/health"
echo ""
echo "2. Configure Twilio webhook URL:"
echo "   ${SERVICE_URL}/webhooks/twilio/status"
echo ""
echo "3. Update Pub/Sub subscription to push to:"
echo "   ${SERVICE_URL}/pubsub/consume"
echo ""
echo "4. Verify secrets are accessible:"
echo "   - twilio-account-sid"
echo "   - twilio-auth-token"
echo "   - sendgrid-api-key"
echo "========================================="

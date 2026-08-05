"""Application settings — loaded from environment variables (mounted from GCP Secret Manager).

SmartHandoff follows TR-021: zero hardcoded credentials. All secrets are injected
as environment variables by Cloud Run via Secret Manager volume mounts.

Usage::
    from app.core.config import get_settings
    settings = get_settings()
    secret = settings.SCIM_CLIENT_SECRET
"""
from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    """Application settings resolved from environment variables at access time.

    Each property reads from ``os.environ`` so tests can monkeypatch the env
    without needing to reload the module.
    """

    @property
    def SCIM_CLIENT_SECRET(self) -> str:
        """Long-lived bearer token issued to the hospital IdP for SCIM provisioning.

        90-day rotation. Stored in GCP Secret Manager as 'scim-client-secret'.
        Mounted as SCIM_CLIENT_SECRET environment variable in Cloud Run (TR-021).

        Raises:
            RuntimeError: If SCIM_CLIENT_SECRET is not set.
        """
        value = os.environ.get("SCIM_CLIENT_SECRET", "")
        if not value:
            raise RuntimeError(
                "SCIM_CLIENT_SECRET environment variable is not set. "
                "Mount it from GCP Secret Manager 'scim-client-secret-{env}'."
            )
        return value

    # --- FHIR / SMART on FHIR OAuth 2.0 (US-016) ---

    @property
    def FHIR_BASE_URL(self) -> str:
        """FHIR R4 server base URL (e.g., 'https://ehr.example.com/fhir').

        Loaded from GCP Secret Manager secret: 'fhir_base_url'.

        Raises:
            RuntimeError: If FHIR_BASE_URL is not set.
        """
        value = os.environ.get("FHIR_BASE_URL", "")
        if not value:
            raise RuntimeError(
                "FHIR_BASE_URL environment variable is not set. "
                "Mount it from GCP Secret Manager 'fhir_base_url'."
            )
        return value

    @property
    def FHIR_CLIENT_ID(self) -> str:
        """SMART on FHIR OAuth 2.0 client ID for client_credentials grant.

        Loaded from GCP Secret Manager secret: 'fhir_client_id'.

        Raises:
            RuntimeError: If FHIR_CLIENT_ID is not set.
        """
        value = os.environ.get("FHIR_CLIENT_ID", "")
        if not value:
            raise RuntimeError(
                "FHIR_CLIENT_ID environment variable is not set. "
                "Mount it from GCP Secret Manager 'fhir_client_id'."
            )
        return value

    @property
    def FHIR_CLIENT_SECRET(self) -> str:
        """SMART on FHIR OAuth 2.0 client secret for client_credentials grant.

        Loaded from GCP Secret Manager secret: 'fhir_client_secret'.

        Raises:
            RuntimeError: If FHIR_CLIENT_SECRET is not set.
        """
        value = os.environ.get("FHIR_CLIENT_SECRET", "")
        if not value:
            raise RuntimeError(
                "FHIR_CLIENT_SECRET environment variable is not set. "
                "Mount it from GCP Secret Manager 'fhir_client_secret'."
            )
        return value

    @property
    def FHIR_SCOPE(self) -> str:
        """OAuth 2.0 scope for FHIR access (default: system/*.read for all resources).

        Can be overridden with specific scopes like 'system/Patient.read system/Encounter.read'.
        """
        return os.environ.get("FHIR_SCOPE", "system/*.read")

    @property
    def FHIR_MRN_SYSTEM(self) -> str:
        """FHIR identifier system for Medical Record Number (MRN).

        Used in Patient?identifier={system}|{mrn} searches.
        Default: 'http://hospital.org/mrn'

        Can be overridden via FHIR_MRN_SYSTEM environment variable for
        organization-specific identifier systems.
        """
        return os.environ.get("FHIR_MRN_SYSTEM", "http://hospital.org/mrn")

    # --- RxNav API (US-030 TASK-003) ---

    @property
    def RXNAV_BASE_URL(self) -> str:
        """Base URL for NIH RxNav REST API.

        Used for RxNorm CUI lookups during medication reconciliation.
        Public API, no authentication required.

        Default: https://rxnav.nlm.nih.gov/REST

        Can be overridden via RXNAV_BASE_URL environment variable for
        testing or alternative RxNav deployments.
        """
        return os.environ.get(
            "RXNAV_BASE_URL", "https://rxnav.nlm.nih.gov/REST"
        )

    @property
    def RXNAV_TIMEOUT_SECONDS(self) -> int:
        """HTTP timeout for RxNav CUI lookup requests (in seconds).

        Default: 5 seconds

        RxNav API is public and generally fast, but timeouts can occur.
        Non-fatal failures (return None for CUI) to allow reconciliation
        to proceed with name-based matching as fallback.

        Can be overridden via RXNAV_TIMEOUT_SECONDS environment variable.
        """
        value = os.environ.get("RXNAV_TIMEOUT_SECONDS", "5")
        try:
            return int(value)
        except ValueError:
            return 5

    # --- GCP Configuration (US-019) ---

    @property
    def GCP_PROJECT_ID(self) -> str:
        """GCP project ID for Pub/Sub topic paths.

        Used for care team alerts and notification requests.
        Loaded from environment variable GCP_PROJECT_ID.

        Raises:
            RuntimeError: If GCP_PROJECT_ID is not set.
        """
        value = os.environ.get("GCP_PROJECT_ID", "")
        if not value:
            raise RuntimeError(
                "GCP_PROJECT_ID environment variable is not set. "
                "Set it in Cloud Run environment configuration."
            )
        return value

    @property
    def PATIENT_EVENTS_TOPIC(self) -> str:
        """Pub/Sub topic for patient-related events (US-042).
        
        Published to by the chatbot agent (EP-008) with URGENCY_FLAG_SET events.
        Format: projects/{project_id}/topics/patient-events
        
        Defaults to using GCP_PROJECT_ID if not explicitly set.
        """
        value = os.environ.get("PATIENT_EVENTS_TOPIC", "")
        if not value:
            project_id = self.GCP_PROJECT_ID
            value = f"projects/{project_id}/topics/patient-events"
        return value

    @property
    def URGENCY_ESCALATION_SUBSCRIPTION(self) -> str:
        """Pub/Sub subscription for URGENCY_FLAG_SET events (US-042).
        
        Consumed by the follow-up care agent's CareEscalationMonitor.
        Format: projects/{project_id}/subscriptions/urgency-escalation-sub
        
        Defaults to using GCP_PROJECT_ID if not explicitly set.
        """
        value = os.environ.get("URGENCY_ESCALATION_SUBSCRIPTION", "")
        if not value:
            project_id = self.GCP_PROJECT_ID
            value = f"projects/{project_id}/subscriptions/urgency-escalation-sub"
        return value

    @property
    def NOTIFICATION_REQUESTS_TOPIC(self) -> str:
        """Pub/Sub topic for outbound notification dispatch requests (US-042, US-064).
        
        Published to by agents when notifications need to be sent.
        Consumed by the notification service for SMS/email dispatch.
        Format: projects/{project_id}/topics/notification-requests
        
        Defaults to using GCP_PROJECT_ID if not explicitly set.
        """
        value = os.environ.get("NOTIFICATION_REQUESTS_TOPIC", "")
        if not value:
            project_id = self.GCP_PROJECT_ID
            value = f"projects/{project_id}/topics/notification-requests"
        return value

    # --- Azure SignalR Service (US-022) ---

    @property
    def AZURE_SIGNALR_CONNECTION_STRING(self) -> str | None:
        """Azure SignalR Service connection string.

        Format: Endpoint=https://<name>.service.signalr.net;AccessKey=<key>;Version=1.0
        Sourced from GCP Secret Manager via environment variable injection at Cloud Run startup.

        Used for real-time task status broadcasts to Angular dashboard clients.

        Returns None if not configured (real-time updates will be disabled).
        """
        value = os.environ.get("AZURE_SIGNALR_CONNECTION_STRING", "")
        if not value:
            return None
        return value

    # --- OTP Authentication (US-065) ---

    @property
    def OTP_PHONE_SALT(self) -> str:
        """Salt for phone number hashing in OTP rate limit keys.

        Used to derive Redis keys like 'otp_rate:{SHA-256(phone_number + salt)}'.
        Prevents phone enumeration from a Redis key dump (SEC-003).

        Stored in GCP Secret Manager as 'smarthandoff-otp-phone-salt'.
        Mounted as OTP_PHONE_SALT environment variable in Cloud Run (TR-021).

        Raises:
            RuntimeError: If OTP_PHONE_SALT is not set.
        """
        value = os.environ.get("OTP_PHONE_SALT", "")
        if not value:
            raise RuntimeError(
                "OTP_PHONE_SALT environment variable is not set. "
                "Mount it from GCP Secret Manager 'smarthandoff-otp-phone-salt'."
            )
        return value

    @property
    def TWILIO_ACCOUNT_SID(self) -> str:
        """Twilio Account SID for Verify API authentication.

        Loaded from GCP Secret Manager secret: 'twilio-account-sid'.

        Raises:
            RuntimeError: If TWILIO_ACCOUNT_SID is not set.
        """
        value = os.environ.get("TWILIO_ACCOUNT_SID", "")
        if not value:
            raise RuntimeError(
                "TWILIO_ACCOUNT_SID environment variable is not set. "
                "Mount it from GCP Secret Manager 'twilio-account-sid'."
            )
        return value

    @property
    def TWILIO_AUTH_TOKEN(self) -> str:
        """Twilio Auth Token for Verify API authentication.

        Loaded from GCP Secret Manager secret: 'twilio-auth-token'.

        Raises:
            RuntimeError: If TWILIO_AUTH_TOKEN is not set.
        """
        value = os.environ.get("TWILIO_AUTH_TOKEN", "")
        if not value:
            raise RuntimeError(
                "TWILIO_AUTH_TOKEN environment variable is not set. "
                "Mount it from GCP Secret Manager 'twilio-auth-token'."
            )
        return value

    @property
    def TWILIO_VERIFY_SID(self) -> str:
        """Twilio Verify Service SID for OTP delivery.

        This is the Service SID from the Twilio Verify product configuration.
        Create a Verify Service in the Twilio Console and copy the SID.

        Loaded from GCP Secret Manager secret: 'twilio-verify-sid'.

        Raises:
            RuntimeError: If TWILIO_VERIFY_SID is not set.
        """
        value = os.environ.get("TWILIO_VERIFY_SID", "")
        if not value:
            raise RuntimeError(
                "TWILIO_VERIFY_SID environment variable is not set. "
                "Mount it from GCP Secret Manager 'twilio-verify-sid'."
            )
        return value

    @property
    def PORTAL_JWT_SECRET(self) -> str:
        """Secret key for validating portal JWT tokens (US-052).

        Used to verify portal_token JWTs that contain patient phone numbers
        for OTP delivery. Shared with the patient portal authentication service.

        Loaded from GCP Secret Manager secret: 'portal-jwt-secret'.

        Raises:
            RuntimeError: If PORTAL_JWT_SECRET is not set.
        """
        value = os.environ.get("PORTAL_JWT_SECRET", "")
        if not value:
            raise RuntimeError(
                "PORTAL_JWT_SECRET environment variable is not set. "
                "Mount it from GCP Secret Manager 'portal-jwt-secret'."
            )
        return value

    # --- CORS Configuration ---

    @property
    def CORS_ORIGINS(self) -> list[str]:
        """Allowed origins for CORS requests.

        Comma-separated list of allowed origins (e.g., frontend URLs).
        Supports wildcards for Cloud Run dynamic URLs:
        - https://*-dev-*.run.app (development)
        - https://*-staging-*.run.app (staging)
        - https://app.smarthandoff.com (production)

        Loaded from CORS_ORIGINS environment variable.
        Defaults to localhost:4200 for local development if not set.

        Example:
            CORS_ORIGINS=http://localhost:4200,https://smarthandoff-frontend-52528248131.us-central1.run.app
        """
        value = os.environ.get(
            "CORS_ORIGINS",
            "http://localhost:4200,https://smarthandoff-frontend-52528248131.us-central1.run.app",
        )
        return [origin.strip() for origin in value.split(",") if origin.strip()]

    # --- Redis (Cloud Memorystore) ---

    @property
    def REDIS_URL(self) -> str:
        """Redis connection URL for Cloud Memorystore.

        Format: redis://host:port or redis://host:port/db_number
        Loaded from environment variable REDIS_URL.

        Raises:
            RuntimeError: If REDIS_URL is not set.
        """
        value = os.environ.get("REDIS_URL", "")
        if not value:
            raise RuntimeError(
                "REDIS_URL environment variable is not set. "
                "Set it in Cloud Run environment configuration or .env file."
            )
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Call ``get_settings.cache_clear()`` in tests to reset after monkeypatching
    environment variables.
    """
    return Settings()

# HL7 Listener — Cloud Run / GKE service
# Base: python:3.12-slim (minimal attack surface per TR-019)
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer cache optimisation)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

# Cloud Run health probe port (HTTP — /health, /ready, /metrics)
EXPOSE 8080
# MLLP TCP port (HL7 ADT ingestion)
EXPOSE 2575

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Run as non-root user (security best practice)
RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

CMD ["python", "-m", "app.main"]

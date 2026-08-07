# Multi-stage Dockerfile for notification-service
# Optimized for production with minimal attack surface

# Stage 1: Build stage
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /build

# Install system dependencies for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Cache-busting argument (forces rebuild from this point)
ARG CACHEBUST=1

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir --no-warn-script-location -r requirements.txt

# Stage 2: Runtime stage
FROM python:3.11-slim

# Create non-root user for security
RUN groupadd -r notifapp && useradd -r -g notifapp notifapp

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /root/.local /home/notifapp/.local

# Copy application code
COPY app/ ./app/
COPY config/ ./config/
COPY alembic.ini .

# Set ownership
RUN chown -R notifapp:notifapp /app

# Switch to non-root user
USER notifapp

# Set Python path
ENV PATH=/home/notifapp/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health').read()"

# Expose port
EXPOSE 8080

# Start application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

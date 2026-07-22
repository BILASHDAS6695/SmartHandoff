# PgBouncer sidecar image for SmartHandoff Cloud Run multi-container deployment.
#
# Build: docker build -t pgbouncer-sidecar backend/pgbouncer/
# Base:  bitnami/pgbouncer (includes glibc, openssl — no root required)
#
# Secrets injected at runtime (Cloud Run secret env vars):
#   PGBOUNCER_AUTH_USER      — the application DB username (e.g. "smarthandoff_app")
#   PGBOUNCER_AUTH_PASSWORD  — the application DB user's password
#   CLOUD_SQL_PRIMARY_HOST   — private IP of the Cloud SQL primary instance

FROM bitnami/pgbouncer:1.22.1

# Copy configuration template (env vars substituted at startup by entrypoint)
COPY pgbouncer.ini /etc/pgbouncer/pgbouncer.ini.template

# Startup script: writes userlist.txt from injected secrets, then execs pgbouncer
COPY entrypoint.sh /entrypoint.sh

USER 0
RUN chmod +x /entrypoint.sh
USER 1001

EXPOSE 5432

ENTRYPOINT ["/entrypoint.sh"]

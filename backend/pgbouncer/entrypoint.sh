#!/bin/sh
# PgBouncer sidecar entrypoint.
# Writes userlist.txt from injected Cloud Run secret env vars at startup.
# Substitutes CLOUD_SQL_PRIMARY_HOST into pgbouncer.ini before starting.
#
# Required env vars (injected by Cloud Run secret bindings):
#   PGBOUNCER_AUTH_USER       — DB username
#   PGBOUNCER_AUTH_PASSWORD   — DB password (plaintext; PgBouncer hashes internally)
#   CLOUD_SQL_PRIMARY_HOST    — Cloud SQL primary private IP

set -e

# Validate required environment variables
: "${PGBOUNCER_AUTH_USER:?PGBOUNCER_AUTH_USER must be set}"
: "${PGBOUNCER_AUTH_PASSWORD:?PGBOUNCER_AUTH_PASSWORD must be set}"
: "${CLOUD_SQL_PRIMARY_HOST:?CLOUD_SQL_PRIMARY_HOST must be set}"

# Write userlist.txt — format: "username" "plaintext-password"
# PgBouncer md5 auth reads from this file.
cat > /etc/pgbouncer/userlist.txt <<EOF
"${PGBOUNCER_AUTH_USER}" "${PGBOUNCER_AUTH_PASSWORD}"
"pgbouncer_admin" "${PGBOUNCER_ADMIN_PASSWORD:-pgbouncer_admin_local}"
EOF

# Substitute CLOUD_SQL_PRIMARY_HOST into the config template
envsubst '${CLOUD_SQL_PRIMARY_HOST}' \
  < /etc/pgbouncer/pgbouncer.ini.template \
  > /etc/pgbouncer/pgbouncer.ini

echo "PgBouncer starting — primary host: ${CLOUD_SQL_PRIMARY_HOST}"
exec pgbouncer /etc/pgbouncer/pgbouncer.ini

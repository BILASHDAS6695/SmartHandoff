#!/usr/bin/env bash
# Run the US-043 chatbot load test against staging.
# Usage: ./run_load_test.sh
# Prerequisites: STAGING_PATIENT_JWTS, STAGING_ENCOUNTER_IDS, TARGET_HOST env vars set.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

pip install -r requirements.txt --quiet

echo "Starting load test: 100 users, 70s run time (10s ramp + 60s steady state)"
locust -f locustfile.py --headless \
    --host "${TARGET_HOST:?TARGET_HOST not set}" \
    --users 100 \
    --spawn-rate 10 \
    --run-time 70s \
    --html="load-test-report-$(date +%Y%m%d-%H%M%S).html" \
    --csv="load-test-$(date +%Y%m%d-%H%M%S)"

echo "Load test complete. HTML report generated."

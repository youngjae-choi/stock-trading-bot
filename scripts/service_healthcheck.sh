#!/bin/bash
# Check the local backend health endpoint and optional systemd unit state.

set -euo pipefail

DEFAULT_URL="http://127.0.0.1:8000/health"
DEFAULT_SERVICE_NAME="stock-trading-bot.service"
HEALTH_URL="${DEFAULT_URL}"
SERVICE_NAME="${DEFAULT_SERVICE_NAME}"
TIMEOUT_SECONDS=5
MODE="run"

usage() {
    # Print supported health-check options for local and systemd usage.
    cat <<'EOF'
Usage:
  ./scripts/service_healthcheck.sh
  ./scripts/service_healthcheck.sh --check

Options:
  --check                 Preview the resolved health-check configuration only.
  --url URL               Override the HTTP health endpoint.
  --service-name NAME     Override the systemd unit name to inspect.
  --timeout SECONDS       Override the curl timeout.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --check)
            MODE="check"
            ;;
        --url)
            HEALTH_URL="$2"
            shift
            ;;
        --service-name)
            SERVICE_NAME="$2"
            shift
            ;;
        --timeout)
            TIMEOUT_SECONDS="$2"
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "FAIL: unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
    shift
done

if [ "${MODE}" = "check" ]; then
    echo "CHECK: service health helper preview"
    echo "health_url=${HEALTH_URL}"
    echo "service_name=${SERVICE_NAME}"
    echo "timeout_seconds=${TIMEOUT_SECONDS}"
    if command -v systemctl >/dev/null 2>&1; then
        echo "systemctl=available"
    else
        echo "systemctl=unavailable"
    fi
    exit 0
fi

if command -v systemctl >/dev/null 2>&1; then
    if systemctl list-unit-files "${SERVICE_NAME}" >/dev/null 2>&1; then
        echo "SYSTEMD STATUS: $(systemctl is-active "${SERVICE_NAME}" 2>/dev/null || echo inactive)"
    else
        echo "SYSTEMD STATUS: ${SERVICE_NAME} not installed"
    fi
fi

echo "HTTP CHECK: ${HEALTH_URL}"
curl --fail --silent --show-error --max-time "${TIMEOUT_SECONDS}" "${HEALTH_URL}"
echo
echo "SUCCESS: health endpoint responded."

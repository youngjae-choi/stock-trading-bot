#!/bin/bash
# Install or preview the stock-trading-bot systemd service.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_PATH="${ROOT_DIR}/systemd/stock-trading-bot.service"
DEFAULT_SERVICE_NAME="stock-trading-bot.service"
WORKDIR="${ROOT_DIR}"
RUN_USER="${SUDO_USER:-${USER}}"
ENV_FILE="${ROOT_DIR}/.env"
SERVICE_NAME="${DEFAULT_SERVICE_NAME}"
MODE="check"
ENABLE_AFTER_INSTALL=0
START_AFTER_INSTALL=0

usage() {
    # Print supported flags for operators who run this helper manually.
    cat <<'EOF'
Usage:
  ./scripts/install_systemd_service.sh --check
  sudo ./scripts/install_systemd_service.sh --install [--enable] [--start]

Options:
  --check                 Preview rendered unit and required commands.
  --install               Copy the rendered unit into /etc/systemd/system.
  --enable                Enable the service after installation.
  --start                 Start the service after installation.
  --service-name NAME     Override the installed unit name.
  --workdir PATH          Override the repo working directory.
  --user USER             Override the service run user.
  --env-file PATH         Override the EnvironmentFile path.
EOF
}

render_service_file() {
    # Render the template with the current install parameters.
    local destination_path="$1"
    sed \
        -e "s|__WORKDIR__|${WORKDIR}|g" \
        -e "s|__RUN_USER__|${RUN_USER}|g" \
        -e "s|__ENV_FILE__|${ENV_FILE}|g" \
        "${TEMPLATE_PATH}" > "${destination_path}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --check)
            MODE="check"
            ;;
        --install)
            MODE="install"
            ;;
        --enable)
            ENABLE_AFTER_INSTALL=1
            ;;
        --start)
            START_AFTER_INSTALL=1
            ;;
        --service-name)
            SERVICE_NAME="$2"
            shift
            ;;
        --workdir)
            WORKDIR="$2"
            shift
            ;;
        --user)
            RUN_USER="$2"
            shift
            ;;
        --env-file)
            ENV_FILE="$2"
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

if [ ! -f "${TEMPLATE_PATH}" ]; then
    echo "FAIL: systemd template not found: ${TEMPLATE_PATH}" >&2
    exit 1
fi

RENDERED_FILE="$(mktemp)"
trap 'rm -f "${RENDERED_FILE}"' EXIT
render_service_file "${RENDERED_FILE}"

if [ "${MODE}" = "check" ]; then
    echo "CHECK: systemd service preview"
    echo "service_name=${SERVICE_NAME}"
    echo "workdir=${WORKDIR}"
    echo "run_user=${RUN_USER}"
    echo "env_file=${ENV_FILE}"
    echo "target=/etc/systemd/system/${SERVICE_NAME}"
    echo
    echo "[Rendered unit]"
    cat "${RENDERED_FILE}"
    echo
    echo "[Next commands]"
    echo "sudo install -m 0644 ${RENDERED_FILE} /etc/systemd/system/${SERVICE_NAME}"
    echo "sudo systemctl daemon-reload"
    echo "sudo systemctl enable ${SERVICE_NAME}"
    echo "sudo systemctl start ${SERVICE_NAME}"
    exit 0
fi

echo "START: installing ${SERVICE_NAME}"
install -m 0644 "${RENDERED_FILE}" "/etc/systemd/system/${SERVICE_NAME}"
systemctl daemon-reload

if [ "${ENABLE_AFTER_INSTALL}" -eq 1 ]; then
    systemctl enable "${SERVICE_NAME}"
fi

if [ "${START_AFTER_INSTALL}" -eq 1 ]; then
    systemctl start "${SERVICE_NAME}"
fi

echo "SUCCESS: installed /etc/systemd/system/${SERVICE_NAME}"
echo "TIP: check status with: systemctl status ${SERVICE_NAME}"

#!/bin/bash
# run.sh - Run or validate the FastAPI backend on port 8000.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

RUN_MODE="${1:-run}"
BACKEND_PID=""

activate_virtualenv() {
    # Activate the project-local venv when present so uvicorn/import paths stay consistent.
    if [ -d ".venv" ]; then
        echo "Activating virtual environment..."
        # shellcheck disable=SC1091
        source .venv/bin/activate
    fi
}

export_pythonpath() {
    # Keep the repo root importable for `python -m uvicorn backend.main:app`.
    if [ -n "${PYTHONPATH:-}" ]; then
        export PYTHONPATH="${PYTHONPATH}:."
    else
        export PYTHONPATH="."
    fi
}

cleanup() {
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
        kill "$BACKEND_PID" >/dev/null 2>&1 || true
    fi
}

on_shutdown() {
    echo "SUCCESS: Server shutdown requested."
    cleanup
    exit 0
}

on_fail() {
    echo "FAIL: Server startup interrupted."
    cleanup
    exit 1
}

trap cleanup EXIT
trap on_shutdown INT TERM
trap on_fail ERR

activate_virtualenv
export_pythonpath

if [ "$RUN_MODE" = "--check" ]; then
    echo "CHECK: validating backend startup prerequisites..."
    python3 -c "import backend.main; print('SUCCESS: backend.main import ok')"
    echo "SUCCESS: run.sh check complete."
    exit 0
fi

if [ "$RUN_MODE" = "--systemd" ] || [ "$RUN_MODE" = "--foreground" ]; then
    echo "START: Backend API Server foreground mode (Port: 8000)..."
    exec python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
fi

echo "START: Backend API Server background mode (Port: 8000)..."
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

for attempt in $(seq 1 20); do
    if curl -fsS "http://127.0.0.1:8000/health" >/dev/null 2>&1; then
        echo "SUCCESS: Backend health check responded."
        HEALTH_OK=1
        break
    fi
    sleep 1
done

if [ "${HEALTH_OK:-0}" -ne 1 ]; then
    echo "FAIL: Backend health check did not respond in time."
    exit 1
fi

echo "SUCCESS: Backend server is running."
echo "Static console URL: http://127.0.0.1:8000/"
echo "Alternate console URL: http://127.0.0.1:8000/console"
echo "Local backend URL: http://127.0.0.1:8000"
echo "Recommended external console URL: http://<your-ddns-host>:18000/console"
echo "Recommended NAT mapping: API and console 18000 -> 8000"
echo "Backend PID: $BACKEND_PID"

# Wait for Ctrl+C
wait

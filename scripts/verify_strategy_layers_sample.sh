#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   scripts/verify_strategy_layers_sample.sh [BASE_URL]
# Example:
#   scripts/verify_strategy_layers_sample.sh http://127.0.0.1:8000

BASE_URL="${1:-http://127.0.0.1:8000}"
WORK_DIR="${WORK_DIR:-/tmp/stb_strategy_layers_check}"
mkdir -p "$WORK_DIR"

HEALTH_HEADERS="$WORK_DIR/health_headers.txt"
HEALTH_BODY="$WORK_DIR/health_body.txt"
SAMPLE_HEADERS="$WORK_DIR/sample_headers.txt"
SAMPLE_BODY="$WORK_DIR/sample_body.txt"
PAYLOAD_FILE="$WORK_DIR/sample_payload.json"

print_file_or_empty() {
  local file_path="$1"
  local max_lines="$2"
  if [[ -f "$file_path" ]]; then
    sed -n "1,${max_lines}p" "$file_path"
  else
    echo "(empty)"
  fi
}

echo "[1/3] health check: $BASE_URL/health"
health_code="$(curl -sS -D "$HEALTH_HEADERS" -o "$HEALTH_BODY" -w '%{http_code}' "$BASE_URL/health" || true)"
echo "health_http_code=$health_code"
echo "--- health raw headers ---"
print_file_or_empty "$HEALTH_HEADERS" 40
echo "--- health raw body ---"
print_file_or_empty "$HEALTH_BODY" 120

if [[ "$health_code" != "200" ]]; then
  echo "health_check_failed=true"
  exit 1
fi

cat > "$PAYLOAD_FILE" <<'JSON'
{
  "universe_filters": [],
  "timing_filters": [],
  "change_filters": []
}
JSON

echo "[2/3] sample call: $BASE_URL/api/v1/kis/strategy/domestic-filter/console"
sample_code="$(curl -sS -D "$SAMPLE_HEADERS" -o "$SAMPLE_BODY" -w '%{http_code}' \
  -H 'Content-Type: application/json' \
  -X POST \
  --data @"$PAYLOAD_FILE" \
  "$BASE_URL/api/v1/kis/strategy/domestic-filter/console" || true)"
echo "sample_http_code=$sample_code"
echo "--- sample raw headers ---"
print_file_or_empty "$SAMPLE_HEADERS" 60
echo "--- sample raw body ---"
print_file_or_empty "$SAMPLE_BODY" 220

echo "[3/3] conditional parse"
content_type="$(awk 'BEGIN{IGNORECASE=1} /^Content-Type:/{print tolower($0)}' "$SAMPLE_HEADERS" | tail -n1 || true)"
trimmed_head="$(tr -d '\r\n\t ' < "$SAMPLE_BODY" | head -c 1 || true)"

if echo "$content_type" | grep -q 'application/json' || [[ "$trimmed_head" == "{" || "$trimmed_head" == "[" ]]; then
  if python3 - <<'PY'
import json
import os
from pathlib import Path

work_dir = os.environ.get("WORK_DIR", "/tmp/stb_strategy_layers_check")
body_path = Path(work_dir) / "sample_body.txt"

try:
    data = json.loads(body_path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)

print("parse_status=success")
print("ok=", data.get("ok"))
print("count=", data.get("count"))
print("strategy_layers=", data.get("strategy_layers"))
PY
  then
    exit 0
  fi

  echo "parse_status=failed"
  echo "raw_response_fallback=true"
  cat "$SAMPLE_BODY"
  exit 1
fi

echo "json_candidate=false"
echo "raw_response_fallback=true"
cat "$SAMPLE_BODY"
exit 1

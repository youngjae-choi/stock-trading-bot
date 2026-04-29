#!/usr/bin/env bash
set -u -o pipefail

SUMMARY_FILE="logs/oracle-playwright-setup-try2-summary.txt"
INSTALL_LOG="logs/oracle-playwright-setup-try2-install.log"
TEST_LOG="logs/oracle-playwright-setup-try2-test.log"
LAST_ERROR_FILE="/tmp/oracle-playwright-last-error.txt"
NPM_CACHE_DIR="/tmp/.npm-stock-trading-bot"

mkdir -p logs "$NPM_CACHE_DIR"
: > "$INSTALL_LOG"
: > "$TEST_LOG"
rm -f "$SUMMARY_FILE" "$LAST_ERROR_FILE"

max_attempts=5
attempt=1
sleep_seconds=3
install_ok=0

while [ "$attempt" -le "$max_attempts" ]; do
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] npm install attempt ${attempt}/${max_attempts}" | tee -a "$INSTALL_LOG"

  if npm install --save-dev @playwright/test --cache "$NPM_CACHE_DIR" >> "$INSTALL_LOG" 2>&1; then
    install_ok=1
    break
  fi

  tail -n 80 "$INSTALL_LOG" > "$LAST_ERROR_FILE"

  if rg -q "EAI_AGAIN|getaddrinfo" "$LAST_ERROR_FILE"; then
    if [ "$attempt" -lt "$max_attempts" ]; then
      echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] transient DNS error detected; retrying in ${sleep_seconds}s" | tee -a "$INSTALL_LOG"
      sleep "$sleep_seconds"
      sleep_seconds=$((sleep_seconds * 2))
    fi
  else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] non-retryable npm failure detected" | tee -a "$INSTALL_LOG"
    break
  fi

  attempt=$((attempt + 1))
done

if [ "$install_ok" -ne 1 ]; then
  {
    echo "status: failed"
    echo "phase: npm_install"
    echo "timestamp_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "reason: npm install failed after retry loop (likely DNS/network issue to registry.npmjs.org)"
    echo "attempts: ${attempt}/${max_attempts}"
    echo ""
    echo "last_error:"
    if [ -f "$LAST_ERROR_FILE" ]; then
      cat "$LAST_ERROR_FILE"
    else
      tail -n 80 "$INSTALL_LOG"
    fi
  } > "$SUMMARY_FILE"
  exit 1
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] npm install succeeded; running Playwright smoke test" | tee -a "$TEST_LOG"

if npm run -s _playwright_test_internal >> "$TEST_LOG" 2>&1; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] test:e2e completed successfully" | tee -a "$TEST_LOG"
  exit 0
fi

{
  echo "status: failed"
  echo "phase: test_e2e"
  echo "timestamp_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "reason: Playwright smoke test failed"
  echo ""
  echo "last_error:"
  tail -n 120 "$TEST_LOG"
} > "$SUMMARY_FILE"

exit 1

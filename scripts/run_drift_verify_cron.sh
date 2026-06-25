#!/usr/bin/env bash
# 6/26 KIS↔DB 드리프트 수정 사후검증 — 무인 1회 실행 (자기삭제 cron).
# 시스템 TZ=UTC. crontab은 07:37 UTC(=16:37 KST, S10 이후)에 이 스크립트를 1회 호출한다.
set -u
REPO=/home/young/repos/stock-trading-bot
LOG="$REPO/logs/drift_verify_20260626.log"
cd "$REPO" || exit 1
{
  echo "===== drift verify run: $(date -Is) (UTC) ====="
  "$REPO/.venv/bin/python" scripts/verify_drift_0626.py 2026-06-26
  echo "===== done: $(date -Is) ====="
} > "$LOG" 2>&1
# 1회성: 실행 후 자신의 cron 라인 제거(이듬해 재발 방지)
crontab -l 2>/dev/null | grep -v 'run_drift_verify_cron.sh' | crontab - 2>/dev/null

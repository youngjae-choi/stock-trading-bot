"""과거 daily_review_reports.day_score 1회 백필 (2026-06-20).

배경: day_score(SSOT) 컬럼이 도입되기 전 생성된 복기 리포트는 day_score=NULL이다.
daily-results 화면을 '저장값만 읽기'(윈도우 의존 재계산 금지)로 전환하면서, 저장값이
없는 날은 '—'로 표시된다. 과거 날짜의 승/패가 화면에서 사라지지 않도록, S10과 **동일한
방식**(7일 lookback + compute_daily_score)으로 day_score를 산출해 1회 영속한다.

- 멱등: 이미 day_score가 있는 행은 건너뛴다.
- 쓰기시점 산출: 화면이 아니라 이 유지보수 스크립트가 계산·저장한다(CQRS 정합).
- WAL/busy_timeout 하에서 단건 UPDATE만 수행(서버 동시 가동 시에도 저위험).

실행: python scripts/backfill_day_score.py [--force]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta

from backend.services.db import get_connection
from backend.services.engine.review_audit import _ensure_review_integrity_columns
from backend.services.engine.trade_pairs import compute_daily_score, get_trade_pairs


def _day_score_for(trade_date: str) -> dict:
    """S10과 동일한 7일 lookback 페어링으로 당일 성적을 산출."""
    start = (datetime.fromisoformat(trade_date) - timedelta(days=7)).strftime("%Y-%m-%d")
    pairs = get_trade_pairs(start, trade_date)
    return compute_daily_score(trade_date, pairs=pairs)


def main(force: bool = False) -> None:
    _ensure_review_integrity_columns()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT trade_date, day_score FROM daily_review_reports ORDER BY trade_date"
        ).fetchall()

        updated = 0
        for r in rows:
            td = str(r["trade_date"])
            if r["day_score"] and not force:
                print(f"  skip {td} (이미 저장됨)")
                continue
            try:
                ds = _day_score_for(td)
            except Exception as exc:
                print(f"  FAIL {td}: {exc}")
                continue
            conn.execute(
                "UPDATE daily_review_reports SET day_score = ? WHERE trade_date = ?",
                (json.dumps(ds, ensure_ascii=False), td),
            )
            updated += 1
            print(f"  set  {td}: {ds['wins']}승 {ds['losses']}패 / 완료 {ds['completed']} / 미청산 {ds['open_positions']}")
        conn.commit()
    print(f"\n완료: {updated}개 행 백필.")


if __name__ == "__main__":
    main(force="--force" in sys.argv)

#!/usr/bin/env python3
"""과거 시세 수집 CLI — 전 보통주 일봉 + 전일 거래대금 상위 N 1분봉 (2026-10-06).

  python scripts/collect_market_history.py run              # 마스터→일봉 증분→분봉(오래된 날부터) 전부. 재개 가능
  python scripts/collect_market_history.py run --top 500 --max-days 1   # 시험: 분봉 하루치만
  python scripts/collect_market_history.py status

매일 장 마감 후(cron) `run` — 당일 일봉·분봉을 이어 붙인다. 동시 실행은 잠금파일로 1개만.
조회 전용(주문 없음). 키/속도는 backend.services.market_data.history.resolve_credentials 참고.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.market_data import history as h  # noqa: E402


async def _run(args) -> None:
    master = h.refresh_master() if args.refresh_master or not (h.ROOT / "master" / "common_stocks.json").exists() else h.load_master()
    if args.limit_symbols:  # 시험용: 거래대금 무관 앞 N종목(+삼성전자 — 거래일 기준)
        master = [m for m in master if m["symbol"] == "005930"] + [m for m in master if m["symbol"] != "005930"][: args.limit_symbols]
    client = h.DataClient()
    try:
        logging.info("START: 수집 credential=%s rps=%.1f 장중정지=%s 종목=%d",
                     "data_key" if h.settings.KIS_DATA_APP_KEY else "trading_key",
                     client.cred.rps, client.cred.pause_market_hours, len(master))
        if not args.skip_daily:
            await h.update_daily(client, master, years=args.daily_years)
        n = await h.backfill_minutes(client, master, top_n=args.top, lookback_days=args.lookback_days,
                                     max_days=args.max_days)
        logging.info("SUCCESS: 분봉 %d일 수집 · 상태=%s", n, json.dumps(h.status(), ensure_ascii=False))
    finally:
        await client.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "status"])
    ap.add_argument("--top", type=int, default=500, help="분봉 유니버스: 전일 거래대금 상위 N")
    ap.add_argument("--daily-years", type=float, default=2.0)
    ap.add_argument("--lookback-days", type=int, default=380)
    ap.add_argument("--max-days", type=int, default=None, help="이번 실행에서 받을 분봉 일수 상한(시험용)")
    ap.add_argument("--skip-daily", action="store_true")
    ap.add_argument("--refresh-master", action="store_true")
    ap.add_argument("--limit-symbols", type=int, default=None, help="시험용: 종목 수 제한")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 요청마다 1줄 → 하루 수십MB
    if args.cmd == "status":
        print(json.dumps(h.status(), ensure_ascii=False, indent=1))
        return 0
    h.ROOT.mkdir(parents=True, exist_ok=True)
    lock = open(h.ROOT / ".collect.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logging.info("다른 수집이 실행 중 — 종료")
        return 0
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""장중 호가·체결 1초 집계 수집 CLI (2026-10-07) — 매매 엔진·DB와 분리된 조회 전용 독립 프로세스.

  python scripts/collect_orderbook.py run      # 평일 08:50~15:35 수집(이전이면 08:50까지 대기), 종료 시 compact
  python scripts/collect_orderbook.py status   # 날짜별 파일 크기·행수·총용량

키는 실전 조회키(KIS_DATA_APP_KEY/SECRET/URL) 전용 — 없으면 즉시 실패(모의키로 대체하지 않음).
중복 실행은 data/market/orderbook/.lock 으로 1개만. SIGTERM/SIGINT 시 flush+compact 후 종료.
상세: backend/services/market_data/orderbook.py
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.market_data import orderbook as ob  # noqa: E402


async def _run() -> int:
    now = datetime.now(ob.KST)
    day = now.strftime("%Y%m%d")
    if now.weekday() >= 5:
        logging.info("[Orderbook] 주말(%s) — 종료", day)
        return 0
    reason = ob.disk_guard()
    if reason:
        logging.error("FAIL: [Orderbook] 디스크 보호 — %s · 수집 안 함", reason)
        return 2
    leftover = ob.compact_pending_days()
    if leftover:
        logging.info("SUCCESS: [Orderbook] 남은 part compact %s", leftover)
    if now.strftime("%H%M") >= ob.END_HHMM:
        logging.info("[Orderbook] %s 이후 — compact만 하고 종료", ob.END_HHMM)
        return 0
    try:
        ob.require_data_key()
    except RuntimeError as e:
        logging.error("FAIL: [Orderbook] %s", e)
        return 2
    sel = ob.load_or_select_symbols(day)
    symbols = [s["symbol"] for s in sel["symbols"]]
    if not symbols:
        logging.error("FAIL: [Orderbook] 선정 종목 0 — 종료")
        return 2
    logging.info("START: [Orderbook] %s 종목 %d개(기준일 %s): %s", day, len(symbols), sel.get("ref_day"),
                 ",".join(symbols))
    col = ob.Collector(day, symbols)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, col.request_stop, sig.name)
    reason = await col.run()
    return 2 if reason == "disk" else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "status"])
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    if args.cmd == "status":
        print(json.dumps(ob.status(), ensure_ascii=False, indent=1))
        return 0
    ob.ROOT.mkdir(parents=True, exist_ok=True)
    lock = open(ob.ROOT / ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logging.info("[Orderbook] 다른 수집이 실행 중 — 종료")
        return 0
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())

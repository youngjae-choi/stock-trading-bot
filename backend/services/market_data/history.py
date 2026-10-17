"""과거 시세 수집기 — 전 보통주 일봉 + 유동성 상위 N 종목 1분봉 (2026-10-06, PM (A) 데이터 기반 재구축).

왜: 전략 검증 데이터가 10초봉 19일·사전선정 20종목뿐(30일 자동삭제)이라 어떤 엣지도 검증 불가였다.
KIS `주식일별분봉조회`(FHKST03010230)는 문서상 '모의 미지원'이지만 실측상 모의 키로도 동작하고
약 1년치(롤링)를 준다 — 오래된 날부터 사라지므로 **오래된 날짜부터** 받는다.

저장(data/market/, git 미추적):
  master/common_stocks.json            — 보통주 목록(KIS 마스터 파일, 그룹 ST·코드끝 0)
  daily/{symbol}.parquet               — 일봉(수정주가) date,open,high,low,close,volume,amount
  minute/{YYYY}/{YYYYMMDD}.parquet     — 그날 유니버스 1분봉 symbol,time,open,high,low,close,volume,cum_amount
  minute/{YYYY}/{YYYYMMDD}.empty       — 그 날짜 KIS 미제공(보존기간 밖) 표시
유니버스(분봉) = **전일** 거래대금 상위 N(룩어헤드 방지). 1분봉은 원주가(무수정).

키: settings.KIS_DATA_APP_KEY(실전계좌, 조회 전용)가 있으면 그 키·도메인·고속(기본 15rps),
없으면 매매 키(모의)를 저속(1rps)·장중 일시정지로 쓴다. 토큰은 data/market/.token_*.json(0600) 캐시(24h).
주문 API는 호출하지 않는다.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import httpx

from ...config import settings

logger = logging.getLogger("MarketHistory")
KST = ZoneInfo("Asia/Seoul")
ROOT = Path(os.environ.get("MARKET_DATA_ROOT") or (Path(__file__).resolve().parents[3] / "data" / "market"))
MASTER_URLS = {
    "kospi": ("https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip", 228),
    "kosdaq": ("https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip", 222),
}
MINUTE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"
DAILY_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
MINUTE_COLS = ["symbol", "time", "open", "high", "low", "close", "volume", "cum_amount"]
DAILY_COLS = ["date", "open", "high", "low", "close", "volume", "amount"]


# ── 보통주 목록 ─────────────────────────────────────────────────────────────
def parse_master(raw: bytes, market: str, tail_len: int) -> list[dict[str, str]]:
    """KIS 마스터(.mst, cp949 고정폭) → 보통주만. 그룹코드는 tail 시작+1 위치 2바이트(실측)."""
    out: list[dict[str, str]] = []
    for line in raw.split(b"\n"):
        line = line.rstrip(b"\r")
        if len(line) <= tail_len + 21:
            continue
        code = line[0:9].decode("cp949", "replace").strip()
        group = line[-tail_len + 1:-tail_len + 3].decode("cp949", "replace")
        name = line[21:-tail_len].decode("cp949", "replace").strip()
        if group != "ST" or len(code) != 6 or not code.isdigit() or code[-1] != "0":
            continue  # ETF/ETN/리츠/우선주 등 제외
        if "스팩" in name:
            continue
        out.append({"symbol": code, "name": name, "market": market})
    return out


def refresh_master() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    with httpx.Client(timeout=30.0) as client:
        for market, (url, tail) in MASTER_URLS.items():
            resp = client.get(url)
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                items += parse_master(zf.read(zf.namelist()[0]), market, tail)
    path = ROOT / "master" / "common_stocks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"as_of": datetime.now(KST).isoformat(), "items": items},
                               ensure_ascii=False), encoding="utf-8")
    logger.info("SUCCESS: [MarketHistory] 보통주 마스터 %d종목", len(items))
    return items


def load_master() -> list[dict[str, str]]:
    path = ROOT / "master" / "common_stocks.json"
    if not path.exists():
        return refresh_master()
    return json.loads(path.read_text(encoding="utf-8"))["items"]


# ── KIS 조회 클라이언트(수집 전용·독립 한도) ─────────────────────────────────
@dataclass
class _Cred:
    key: str
    secret: str
    base_url: str
    rps: float
    pause_market_hours: bool


def resolve_credentials() -> _Cred:
    if settings.KIS_DATA_APP_KEY and settings.KIS_DATA_APP_SECRET:
        return _Cred(settings.KIS_DATA_APP_KEY, settings.KIS_DATA_APP_SECRET, settings.KIS_DATA_URL,
                     float(settings.KIS_DATA_RPS or 15.0), False)
    # 모의(VTS) 시세조회 실측 한도 ≈ 1건/초(2rps면 절반이 EGW00201 → 재시도로 실효 1건/초, 2026-10-06)
    return _Cred(settings.KIS_APP_KEY, settings.KIS_APP_SECRET, settings.KIS_URL,
                 float(settings.KIS_DATA_RPS or 1.0), True)


def in_market_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now(KST)
    return now.weekday() < 5 and "08:30" <= now.strftime("%H:%M") < "15:45"


class DataClient:
    """조회 전용 KIS 클라이언트 — 자체 토큰 캐시·속도제한·EGW00201 재시도."""

    def __init__(self, cred: _Cred | None = None):
        self.cred = cred or resolve_credentials()
        self._token: str | None = None
        self._exp = 0.0
        self._last = 0.0
        self.throttled = 0                # EGW00201(초당 한도) 거절 횟수 — 진행 로그로 rps 적정성 확인
        self._gate = asyncio.Lock()       # 요청 시작 간격(1/rps) 직렬화 — 응답 대기는 겹친다
        self._tok_lock = asyncio.Lock()   # 동시 요청이 토큰을 중복 발급(EGW00133)하지 않게
        self._http = httpx.AsyncClient(timeout=15.0)
        tag = hashlib.sha256((self.cred.base_url + self.cred.key).encode()).hexdigest()[:10]
        self._cache = ROOT / f".token_{tag}.json"

    @property
    def concurrency(self) -> int:
        """동시 요청 수. 응답 지연(~0.9s)이 간격보다 길어 직렬이면 rps가 1 근처에 갇힌다."""
        return max(1, min(8, int(self.cred.rps)))

    async def close(self) -> None:
        await self._http.aclose()

    async def _token_get(self) -> str:
        async with self._tok_lock:
            return await self._token_get_locked()

    async def _token_get_locked(self) -> str:
        if self._token and self._exp > time.time() + 600:
            return str(self._token)
        try:
            d = json.loads(self._cache.read_text())
            if d["exp"] > time.time() + 600:
                self._token, self._exp = str(d["token"]), float(d["exp"])
                return self._token
        except Exception:
            pass
        for attempt in range(4):
            r = await self._http.post(f"{self.cred.base_url}/oauth2/tokenP", json={
                "grant_type": "client_credentials", "appkey": self.cred.key, "appsecret": self.cred.secret})
            body = r.json() if r.content else {}
            if body.get("access_token"):
                self._token = str(body["access_token"])
                self._exp = time.time() + max(60, int(body.get("expires_in", 86400)))
                self._cache.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self._cache, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    json.dump({"token": self._token, "exp": self._exp}, f)
                return str(self._token)
            logger.warning("WARN: [MarketHistory] 토큰 발급 실패(%s) — 65초 후 재시도: %s",
                           attempt + 1, body.get("error_code") or r.status_code)
            await asyncio.sleep(65)
        raise RuntimeError("KIS 데이터 토큰 발급 실패")

    async def get(self, path: str, tr_id: str, params: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(6):
            if self.cred.pause_market_hours:
                while in_market_hours():
                    await asyncio.sleep(60)  # 모의 키 공유 — 장중엔 매매 엔진 호출한도 양보
            async with self._gate:
                wait = self._last + 1.0 / self.cred.rps - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last = time.monotonic()
            token = await self._token_get()
            try:
                r = await self._http.get(f"{self.cred.base_url}{path}", params=params, headers={
                    "content-type": "application/json", "authorization": f"Bearer {token}",
                    "appkey": self.cred.key, "appsecret": self.cred.secret, "tr_id": tr_id, "custtype": "P"})
            except httpx.HTTPError as exc:
                logger.warning("WARN: [MarketHistory] HTTP 오류 재시도 %s — %s", attempt + 1, exc)
                await asyncio.sleep(2 * (attempt + 1))
                continue
            body = r.json() if r.content else {}
            if r.status_code == 401 or body.get("msg_cd") in ("EGW00123", "EGW00121"):
                self._token, self._exp = None, 0.0  # 만료·무효 토큰 → 재발급
                try:
                    self._cache.unlink()
                except OSError:
                    pass
                continue
            if body.get("msg_cd") == "EGW00201":
                self.throttled += 1
            if body.get("msg_cd") == "EGW00201" or r.status_code >= 500:
                await asyncio.sleep(1.0 + attempt)  # 초당 한도 초과·서버 오류
                continue
            return body
        raise RuntimeError(f"KIS 조회 실패(재시도 소진) {path} {params.get('FID_INPUT_ISCD')}")


# ── 파싱 ───────────────────────────────────────────────────────────────────
def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def parse_minute_rows(rows: Iterable[dict[str, Any]], symbol: str, day: str) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        if str(r.get("stck_bsop_date")) != day:
            continue
        out.append({"symbol": symbol, "time": str(r.get("stck_cntg_hour") or "")[:4],
                    "open": _num(r.get("stck_oprc")), "high": _num(r.get("stck_hgpr")),
                    "low": _num(r.get("stck_lwpr")), "close": _num(r.get("stck_prpr")),
                    "volume": _num(r.get("cntg_vol")), "cum_amount": _num(r.get("acml_tr_pbmn"))})
    return out


async def fetch_minutes(client: DataClient, symbol: str, day: str) -> list[dict[str, Any]]:
    """한 종목·하루 1분봉 전체(120개씩 역순 페이징, 09:00까지). day=YYYYMMDD."""
    hour, bars, seen = "153000", [], set()
    for _ in range(6):
        body = await client.get(MINUTE_PATH, "FHKST03010230", {
            "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol, "FID_INPUT_HOUR_1": hour,
            "FID_INPUT_DATE_1": day, "FID_PW_DATA_INCU_YN": "Y", "FID_FAKE_TICK_INCU_YN": ""})
        rows = parse_minute_rows(body.get("output2") or [], symbol, day)
        rows = [r for r in rows if r["time"] not in seen]
        if not rows:
            break
        seen.update(r["time"] for r in rows)
        bars += rows
        earliest = min(r["time"] for r in rows)
        if earliest <= "0900":
            break
        t = datetime.strptime(earliest, "%H%M") - timedelta(minutes=1)
        hour = t.strftime("%H%M00")
    return sorted(bars, key=lambda r: r["time"])


async def fetch_daily(client: DataClient, symbol: str, start: str, end: str) -> list[dict[str, Any]]:
    """일봉(수정주가) start~end(YYYYMMDD). 100개씩 역순 페이징."""
    out: dict[str, dict[str, Any]] = {}
    hi = end
    for _ in range(20):
        body = await client.get(DAILY_PATH, "FHKST03010100", {
            "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol, "FID_INPUT_DATE_1": start,
            "FID_INPUT_DATE_2": hi, "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"})
        rows = [r for r in (body.get("output2") or []) if r.get("stck_bsop_date")]
        new = 0
        for r in rows:
            d = str(r["stck_bsop_date"])
            if d not in out and start <= d <= end:
                out[d] = {"date": d, "open": _num(r.get("stck_oprc")), "high": _num(r.get("stck_hgpr")),
                          "low": _num(r.get("stck_lwpr")), "close": _num(r.get("stck_clpr")),
                          "volume": _num(r.get("acml_vol")), "amount": _num(r.get("acml_tr_pbmn"))}
                new += 1
        if not rows or new == 0 or len(rows) < 100:
            break
        oldest = min(str(r["stck_bsop_date"]) for r in rows)
        if oldest <= start:
            break
        hi = (datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    return [out[k] for k in sorted(out)]


# ── 저장(Parquet) ──────────────────────────────────────────────────────────
def _pd():
    import pandas as pd  # 지연 import(서버 런타임 무관)
    return pd


def daily_path(symbol: str) -> Path:
    return ROOT / "daily" / f"{symbol}.parquet"


def minute_path(day: str) -> Path:
    return ROOT / "minute" / day[:4] / f"{day}.parquet"


def read_daily(symbol: str):
    p = daily_path(symbol)
    pd = _pd()
    return pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=DAILY_COLS)


def write_daily(symbol: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    pd = _pd()
    old = read_daily(symbol)
    df = pd.concat([old, pd.DataFrame(rows, columns=DAILY_COLS)]) if len(old) else pd.DataFrame(rows, columns=DAILY_COLS)
    df = df.drop_duplicates("date", keep="last").sort_values("date")
    p = daily_path(symbol)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(p)
    return len(rows)


def write_minute_day(day: str, rows: list[dict[str, Any]]) -> None:
    pd = _pd()
    p = minute_path(day)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        p.with_suffix(".empty").write_text("KIS 미제공(보존기간 밖) 또는 휴장")
        return
    tmp = p.with_suffix(".tmp")
    pd.DataFrame(rows, columns=MINUTE_COLS).to_parquet(tmp, index=False)
    tmp.replace(p)


def minute_done(day: str) -> bool:
    p = minute_path(day)
    return p.exists() or p.with_suffix(".empty").exists()


# ── 유니버스·작업 ───────────────────────────────────────────────────────────
def trading_days(reference: str = "005930") -> list[str]:
    df = read_daily(reference)
    return list(df["date"]) if len(df) else []


def load_amounts(master: list[dict[str, str]]) -> dict[str, list[tuple[float, str]]]:
    """일봉 전체를 한 번 읽어 날짜→[(거래대금, 종목)] 표를 만든다(유니버스 선정용)."""
    by_day: dict[str, list[tuple[float, str]]] = {}
    for item in master:
        df = read_daily(item["symbol"])
        for d, a in zip(df["date"], df["amount"]):
            by_day.setdefault(str(d), []).append((float(a), item["symbol"]))
    return by_day


def liquidity_universe(prev_day: str, amounts: dict[str, list[tuple[float, str]]], top_n: int) -> list[str]:
    """prev_day 거래대금 상위 top_n 보통주(룩어헤드 방지 — 당일이 아닌 전일 기준)."""
    return [s for _, s in sorted(amounts.get(prev_day, []), reverse=True)[:top_n]]


async def _map_bounded(n: int, items: list[Any], fn) -> None:
    sem = asyncio.Semaphore(n)

    async def one(x):
        async with sem:
            await fn(x)

    await asyncio.gather(*(one(x) for x in items))


def _daily_final(day: str) -> bool:
    """장 마감 후(또는 이후 날짜의 실행에서) 받아 확정된 일봉 날짜인지 — 마커 파일로 기록."""
    return (ROOT / f".daily_final_{day}").exists()


def daily_fetch_start(last: str, final: bool) -> str:
    """증분 시작일. 마지막 행이 확정이면 다음날부터, 장중에 받은 미완성 행일 수 있으면 그 날부터 다시 받는다."""
    if final:
        return (datetime.strptime(last, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
    return last


async def update_daily(client: DataClient, master: list[dict[str, str]], years: float = 2.0) -> int:
    now = datetime.now(KST)
    today = now.strftime("%Y%m%d")
    after_close = now.strftime("%H:%M") >= "15:45"
    floor = (now - timedelta(days=int(365 * years))).strftime("%Y%m%d")
    total = done = 0
    lasts: set[str] = set()

    async def one(item: dict[str, str]) -> None:
        nonlocal total, done
        old = read_daily(item["symbol"])
        start = floor
        if len(old):
            last = str(old["date"].max())
            lasts.add(last)
            start = daily_fetch_start(last, _daily_final(last))
        if start <= today:
            try:
                total += write_daily(item["symbol"], await fetch_daily(client, item["symbol"], start, today))
            except Exception as exc:
                logger.warning("WARN: [MarketHistory] 일봉 실패 %s — %s", item["symbol"], exc)
        done += 1
        if done % 200 == 0:
            logger.info("INFO: [MarketHistory] 일봉 진행 %d/%d (+%d행, 한도거절 %d)",
                        done, len(master), total, client.throttled)

    await _map_bounded(client.concurrency, master, one)
    for d in lasts | {today}:  # 이번 실행이 그 날 마감 후거나 이후 날짜면 확정 처리
        if d < today or after_close:
            (ROOT / f".daily_final_{d}").touch()
    logger.info("SUCCESS: [MarketHistory] 일봉 갱신 완료 +%d행", total)
    return total


async def backfill_minutes(client: DataClient, master: list[dict[str, str]], top_n: int = 500,
                           lookback_days: int = 380, max_days: int | None = None) -> int:
    """오래된 날짜부터 미수집 날짜의 1분봉을 받는다(롤링 보존 — 오래된 날부터 사라짐)."""
    days = trading_days()
    floor = (datetime.now(KST) - timedelta(days=lookback_days)).strftime("%Y%m%d")
    today = datetime.now(KST).strftime("%Y%m%d")
    now_hm = datetime.now(KST).strftime("%H:%M")
    done_days = 0
    amounts = load_amounts(master)
    for idx in range(1, len(days)):
        day, prev = days[idx], days[idx - 1]
        if day < floor or minute_done(day):
            continue
        if day == today and now_hm < "15:45":
            continue  # 장 마감 전 당일은 미완성
        universe = liquidity_universe(prev, amounts, top_n)
        if not universe:
            continue
        probe = await fetch_minutes(client, universe[0], day)
        if not probe:
            write_minute_day(day, [])  # 보존기간 밖 — 다시 시도하지 않음
            logger.info("INFO: [MarketHistory] %s 분봉 미제공 → 건너뜀", day)
            continue
        rows = list(probe)

        async def one(sym: str) -> None:
            try:
                rows.extend(await fetch_minutes(client, sym, day))
            except Exception as exc:
                logger.warning("WARN: [MarketHistory] 분봉 실패 %s %s — %s", day, sym, exc)

        await _map_bounded(client.concurrency, universe[1:], one)
        write_minute_day(day, rows)
        done_days += 1
        logger.info("SUCCESS: [MarketHistory] %s 분봉 %d종목 %d행 (한도거절 누적 %d)",
                    day, len(universe), len(rows), client.throttled)
        if max_days and done_days >= max_days:
            break
    return done_days


# ── 지수·ETF(2026-10-16) ───────────────────────────────────────────────────
# 왜: 10-07~10-16 KOSPI −20.6% 폭락 때 인버스·지수 헤지를 검증할 데이터가 없었다(보통주만 수집).
# ETF는 보통주 백테스트(거래대금 상위 유니버스)에 섞이면 안 되므로 **별도 폴더**에 둔다.
#   daily_etf/{symbol}.parquet · minute_etf/{YYYY}/{YYYYMMDD}.parquet · index/{code}.parquet
EXTRA_ETFS = {"069500": "KODEX 200", "114800": "KODEX 인버스",
              "229200": "KODEX 코스닥150", "251340": "KODEX 코스닥150선물인버스"}
INDEXES = {"0001": "KOSPI", "1001": "KOSDAQ", "2001": "KOSPI200"}
INDEX_DAILY_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice"
INDEX_COLS = ["date", "open", "high", "low", "close", "volume", "amount"]


def etf_daily_path(symbol: str) -> Path:
    return ROOT / "daily_etf" / f"{symbol}.parquet"


def etf_minute_path(day: str) -> Path:
    return ROOT / "minute_etf" / day[:4] / f"{day}.parquet"


def index_path(code: str) -> Path:
    return ROOT / "index" / f"{code}.parquet"


def _merge_write(p: Path, rows: list[dict[str, Any]], cols: list[str], key: str = "date") -> int:
    if not rows:
        return 0
    pd = _pd()
    new = pd.DataFrame(rows, columns=cols)
    df = pd.concat([pd.read_parquet(p), new]) if p.exists() else new
    df = df.drop_duplicates(key, keep="last").sort_values(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(p)
    return len(rows)


def parse_index_rows(rows: Iterable[dict[str, Any]], start: str, end: str) -> list[dict[str, Any]]:
    """FHKUP03500100 output2 → 일봉 행. 날짜 범위 밖·빈 행 제외."""
    out = []
    for r in rows:
        d = str(r.get("stck_bsop_date") or "")
        if not d or not (start <= d <= end):
            continue
        out.append({"date": d, "open": _num(r.get("bstp_nmix_oprc")), "high": _num(r.get("bstp_nmix_hgpr")),
                    "low": _num(r.get("bstp_nmix_lwpr")), "close": _num(r.get("bstp_nmix_prpr")),
                    "volume": _num(r.get("acml_vol")), "amount": _num(r.get("acml_tr_pbmn"))})
    return out


async def fetch_index_daily(client: DataClient, code: str, start: str, end: str) -> list[dict[str, Any]]:
    """업종지수 일봉 start~end. 역순 페이징(한 번에 약 100행)."""
    out: dict[str, dict[str, Any]] = {}
    hi = end
    for _ in range(20):
        body = await client.get(INDEX_DAILY_PATH, "FHKUP03500100", {
            "FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": code, "FID_INPUT_DATE_1": start,
            "FID_INPUT_DATE_2": hi, "FID_PERIOD_DIV_CODE": "D"})
        rows = parse_index_rows(body.get("output2") or [], start, end)
        new = [r for r in rows if r["date"] not in out]
        for r in new:
            out[r["date"]] = r
        if not new:
            break
        oldest = min(r["date"] for r in new)
        if oldest <= start:
            break
        hi = (datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    return [out[k] for k in sorted(out)]


def _incremental_start(p: Path, floor: str) -> str:
    """기존 파일 마지막 날짜(미확정일 수 있으니 그 날부터 다시) 또는 floor."""
    if not p.exists():
        return floor
    return str(_pd().read_parquet(p, columns=["date"])["date"].max())


async def update_extras(client: DataClient, years: float = 2.0, lookback_days: int = 380) -> dict[str, int]:
    """지수 일봉 + ETF 일봉 + ETF 1분봉(미수집 날짜만, 오래된 날부터). 실패는 경고만(보통주 수집과 독립)."""
    now = datetime.now(KST)
    today = now.strftime("%Y%m%d")
    floor = (now - timedelta(days=int(365 * years))).strftime("%Y%m%d")
    res = {"index": 0, "etf_daily": 0, "etf_minute_days": 0}
    for code in INDEXES:
        try:
            p = index_path(code)
            res["index"] += _merge_write(p, await fetch_index_daily(client, code, _incremental_start(p, floor), today),
                                         INDEX_COLS)
        except Exception as exc:
            logger.warning("WARN: [MarketHistory] 지수 일봉 실패 %s — %s", code, exc)
    for sym in EXTRA_ETFS:
        try:
            p = etf_daily_path(sym)
            res["etf_daily"] += _merge_write(p, await fetch_daily(client, sym, _incremental_start(p, floor), today),
                                             DAILY_COLS)
        except Exception as exc:
            logger.warning("WARN: [MarketHistory] ETF 일봉 실패 %s — %s", sym, exc)
    mfloor = (now - timedelta(days=lookback_days)).strftime("%Y%m%d")
    after_close = now.strftime("%H:%M") >= "15:45"
    for day in trading_days():
        p = etf_minute_path(day)
        if day < mfloor or p.exists() or p.with_suffix(".empty").exists() or (day == today and not after_close):
            continue
        rows: list[dict[str, Any]] = []
        for sym in EXTRA_ETFS:
            try:
                rows.extend(await fetch_minutes(client, sym, day))
            except Exception as exc:
                logger.warning("WARN: [MarketHistory] ETF 분봉 실패 %s %s — %s", day, sym, exc)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            p.with_suffix(".empty").write_text("KIS 미제공(보존기간 밖) 또는 휴장")
            continue
        tmp = p.with_suffix(".tmp")
        _pd().DataFrame(rows, columns=MINUTE_COLS).to_parquet(tmp, index=False)
        tmp.replace(p)
        res["etf_minute_days"] += 1
    logger.info("SUCCESS: [MarketHistory] 지수·ETF 갱신 %s", res)
    return res


def status() -> dict[str, Any]:
    minute_files = sorted((ROOT / "minute").glob("*/*.parquet")) if (ROOT / "minute").exists() else []
    daily_files = list((ROOT / "daily").glob("*.parquet")) if (ROOT / "daily").exists() else []
    size = sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file()) if ROOT.exists() else 0
    return {"daily_symbols": len(daily_files), "minute_days": len(minute_files),
            "minute_first": minute_files[0].stem if minute_files else None,
            "minute_last": minute_files[-1].stem if minute_files else None,
            "size_mb": round(size / 1e6, 1), "credential": "data_key" if settings.KIS_DATA_APP_KEY else "trading_key(mock,slow)"}

"""장중 호가·체결 1초 집계 수집기 (2026-10-07) — 매매 엔진·SQLite DB와 완전 분리, 조회 전용.

왜: 진입 타이밍(바닥전 매수·꼭지 추격) 연구에 1분봉으론 부족하다. 원시 틱 전체 저장은 용량이 크므로
호가(10단)는 '초별 마지막 상태(변화 있을 때만)', 체결은 '초별 집계(매수/매도 주도·큰 체결 분리)'로만 남긴다.

키: settings.KIS_DATA_APP_KEY/SECRET/URL(실전 조회키) **전용**. 없으면 즉시 실패한다 — 모의(매매) 키를
쓰면 매매 엔진의 웹소켓 41슬롯을 뺏기 때문. 종목 20개 × (H0STASP0 호가 + H0STCNT0 체결) = 40슬롯.

저장(data/market/orderbook/, git 미추적):
  YYYYMMDD/symbols.json            — 그날 고정 종목(직전 완료 거래일 거래대금 상위 20, 종가≥5,000)
  YYYYMMDD/book_HHMM.parquet       — 10분마다 쓰는 part(원자적 tmp→rename)
  YYYYMMDD/flow_HHMM.parquet
  YYYYMMDD/book.parquet, flow.parquet — 종료 시 part 합본(zstd, symbol·sec 정렬). 합친 part 이름은
                                       parquet 메타데이터에 기록 → 재compact 멱등(이중 합산 없음)
  YYYYMMDD/_anomaly.log            — 필드수 불일치 등 원문 앞 300자(하루 최대 20건)
시간은 거래소 시각(BSOP_HOUR/STCK_CNTG_HOUR, HHMMSS 정수). 08:30 이전 레코드는 버린다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from . import history as h

logger = logging.getLogger("Orderbook")
KST = h.KST
ROOT: Path = h.ROOT / "orderbook"

WS_URL = "ws://ops.koreainvestment.com:21000"
TR_BOOK = "H0STASP0"
TR_FLOW = "H0STCNT0"
N_SYMBOLS = 20
WS_SLOT_LIMIT = 41
MIN_CLOSE = 5_000
BIG_TRADE_AMT = 30_000_000
MAX_BYTES = 8 * 1024 ** 3        # data/market/orderbook 총 용량 상한
MIN_FREE_BYTES = 5 * 1024 ** 3   # 파일시스템 여유공간 하한
FLUSH_SEC = 600
ANOMALY_MAX_PER_DAY = 20      # TR별 하루 상한(한 TR이 다른 TR의 샘플 자리를 다 쓰지 않게)
MIN_SEC = 83000                  # 08:30:00 이전 레코드 버림

START_HHMM = "0850"
END_HHMM = "1535"
HOLIDAY_CHECK_HHMM = "0915"
RECV_TIMEOUT_SEC = 90            # 이 시간 동안 아무 메시지(PINGPONG 포함)도 없으면 재연결

# ── 필드 정의 ───────────────────────────────────────────────────────────────
BOOK_FIELDS = (
    ["MKSC_SHRN_ISCD", "BSOP_HOUR", "HOUR_CLS_CODE"]
    + [f"ASKP{i}" for i in range(1, 11)] + [f"BIDP{i}" for i in range(1, 11)]
    + [f"ASKP_RSQN{i}" for i in range(1, 11)] + [f"BIDP_RSQN{i}" for i in range(1, 11)]
    + ["TOTAL_ASKP_RSQN", "TOTAL_BIDP_RSQN", "OVTM_TOTAL_ASKP_RSQN", "OVTM_TOTAL_BIDP_RSQN",
       "ANTC_CNPR", "ANTC_CNQN", "ANTC_VOL", "ANTC_CNTG_VRSS", "ANTC_CNTG_VRSS_SIGN",
       "ANTC_CNTG_PRDY_CTRT", "ACML_VOL", "TOTAL_ASKP_RSQN_ICDC", "TOTAL_BIDP_RSQN_ICDC",
       "OVTM_TOTAL_ASKP_ICDC", "OVTM_TOTAL_BIDP_ICDC", "STCK_DEAL_CLS_CODE"]
)
FLOW_FIELDS = [
    "MKSC_SHRN_ISCD", "STCK_CNTG_HOUR", "STCK_PRPR", "PRDY_VRSS_SIGN", "PRDY_VRSS", "PRDY_CTRT",
    "WGHN_AVRG_STCK_PRC", "STCK_OPRC", "STCK_HGPR", "STCK_LWPR", "ASKP1", "BIDP1", "CNTG_VOL",
    "ACML_VOL", "ACML_TR_PBMN", "SELN_CNTG_CSNU", "SHNU_CNTG_CSNU", "NTBY_CNTG_CSNU", "CTTR",
    "SELN_CNTG_SMTN", "SHNU_CNTG_SMTN", "CCLD_DVSN", "SHNU_RATE", "PRDY_VOL_VRSS_ACML_VOL_RATE",
    "OPRC_HOUR", "OPRC_VRSS_PRPR_SIGN", "OPRC_VRSS_PRPR", "HGPR_HOUR", "HGPR_VRSS_PRPR_SIGN",
    "HGPR_VRSS_PRPR", "LWPR_HOUR", "LWPR_VRSS_PRPR_SIGN", "LWPR_VRSS_PRPR", "BSOP_DATE",
    "NEW_MKOP_CLS_CODE", "TRHT_YN", "ASKP_RSQN1", "BIDP_RSQN1", "TOTAL_ASKP_RSQN", "TOTAL_BIDP_RSQN",
    "VOL_TNRT", "PRDY_SMNS_HOUR_ACML_VOL", "PRDY_SMNS_HOUR_ACML_VOL_RATE", "HOUR_CLS_CODE",
    "MRKT_TRTM_CLS_CODE", "VI_STND_PRC",
]
assert len(BOOK_FIELDS) == 59 and len(FLOW_FIELDS) == 46
FIELD_COUNT = {TR_BOOK: len(BOOK_FIELDS), TR_FLOW: len(FLOW_FIELDS)}
_BI = {n: i for i, n in enumerate(BOOK_FIELDS)}
_FI = {n: i for i, n in enumerate(FLOW_FIELDS)}

# ── 저장 컬럼 ───────────────────────────────────────────────────────────────
BOOK_PX_COLS = [f"ask_px{i}" for i in range(1, 11)] + [f"bid_px{i}" for i in range(1, 11)]
BOOK_QTY_COLS = [f"ask_qty{i}" for i in range(1, 11)] + [f"bid_qty{i}" for i in range(1, 11)]
BOOK_VALUE_COLS = BOOK_PX_COLS + BOOK_QTY_COLS + ["tot_ask", "tot_bid", "acml_vol"]
BOOK_COLS = ["symbol", "sec"] + BOOK_VALUE_COLS + ["n_updates"]
BOOK_DTYPES = {"symbol": "string", "sec": "int32", **{c: "int32" for c in BOOK_PX_COLS},
               **{c: "int64" for c in BOOK_QTY_COLS}, "tot_ask": "int64", "tot_bid": "int64",
               "acml_vol": "int64", "n_updates": "int32"}
FLOW_SUM_COLS = ["n_trades", "buy_qty", "sell_qty", "other_qty", "buy_amt", "sell_amt",
                 "big_buy_amt", "big_sell_amt"]
FLOW_COLS = ["symbol", "sec"] + FLOW_SUM_COLS + ["first_px", "last_px", "high_px", "low_px", "acml_vol"]
FLOW_DTYPES = {"symbol": "string", "sec": "int32", "n_trades": "int32", "buy_qty": "int64",
               "sell_qty": "int64", "other_qty": "int64", "buy_amt": "int64", "sell_amt": "int64",
               "big_buy_amt": "int64", "big_sell_amt": "int64", "first_px": "int32", "last_px": "int32",
               "high_px": "int32", "low_px": "int32", "acml_vol": "int64"}


# ── 파싱(순수 함수) ─────────────────────────────────────────────────────────
@dataclass
class Parsed:
    tr_id: str
    records: list[list[str]]
    anomaly: str | None = None   # None이면 정상
    width: int = 0               # 실제 레코드 폭(문서 정의보다 클 수 있음)


def parse_data_message(raw: str) -> Parsed | None:
    """'0|TR_ID|COUNT|BODY' → 레코드 목록. COUNT개 레코드가 '^'로 이어 붙어 있다(첫 레코드만 읽지 않는다).

    관심 TR이 아니거나 암호화('1|')면 None. 필드 수가 정의의 배수가 아니거나 COUNT와 안 맞으면 anomaly.
    """
    parts = raw.split("|", 3)
    if len(parts) != 4 or parts[0] != "0":
        return None
    tr_id, count_s, body = parts[1], parts[2], parts[3]
    n = FIELD_COUNT.get(tr_id)
    if n is None:
        return None
    fields = body.split("^")
    if fields and fields[-1] == "" and len(fields) % max(1, _safe_int(count_s)) != 0:
        fields = fields[:-1]  # 끝 구분자 '^' 로 생긴 빈 필드
    try:
        count = int(count_s)
    except ValueError:
        return Parsed(tr_id, [], f"bad count {count_s!r}")
    if count <= 0 or len(fields) % count != 0:
        return Parsed(tr_id, [], f"field_count {len(fields)} not divisible by count {count}")
    width = len(fields) // count
    if width < n:
        return Parsed(tr_id, [], f"record width {width} < documented {n}")
    # 실데이터(2026-10-08): H0STASP0 레코드 폭 63(문서 59) — 앞 59개는 문서 순서와 일치, 뒤에 필드가 추가됨.
    # 레코드 폭은 COUNT로 나눠 구하고, 문서에 정의된 앞쪽 n개만 읽는다(추가 필드는 무시).
    return Parsed(tr_id, [fields[i * width:i * width + n] for i in range(count)], None, width)


def _safe_int(v: str) -> int:
    try:
        return int(v)
    except ValueError:
        return 0


def _int(v: str) -> int:
    v = v.strip()
    if not v:
        return 0
    return int(v) if v.lstrip("-").isdigit() else int(float(v))


def _sec(v: str) -> int:
    v = v.strip()
    if len(v) != 6 or not v.isdigit():
        raise ValueError(f"bad time {v!r}")
    s = int(v)
    if s // 10000 > 23 or (s // 100) % 100 > 59 or s % 100 > 59:
        raise ValueError(f"bad time {v!r}")
    return s


def _symbol(v: str) -> str:
    v = v.strip()
    if len(v) != 6 or not v.isalnum():
        raise ValueError(f"bad symbol {v!r}")
    return v


def book_record(rec: list[str]) -> tuple[str, int, dict[str, int], str]:
    """H0STASP0 1레코드 → (symbol, sec, values, kind). kind: 'ok'|'one_sided'. 이상하면 ValueError.

    검증: 연속매매(HOUR_CLS_CODE='0')에선 ASKP1 > BIDP1 > 0. 단 상·하한가처럼 한쪽 호가만 0인 경우는
    정상('one_sided')으로 저장. 예상체결(동시호가) 구간은 호가가 교차할 수 있어 교차 검사는 생략.
    """
    sym = _symbol(rec[_BI["MKSC_SHRN_ISCD"]])
    sec = _sec(rec[_BI["BSOP_HOUR"]])
    vals: dict[str, int] = {}
    for i in range(1, 11):
        vals[f"ask_px{i}"] = _int(rec[_BI[f"ASKP{i}"]])
        vals[f"bid_px{i}"] = _int(rec[_BI[f"BIDP{i}"]])
        vals[f"ask_qty{i}"] = _int(rec[_BI[f"ASKP_RSQN{i}"]])
        vals[f"bid_qty{i}"] = _int(rec[_BI[f"BIDP_RSQN{i}"]])
    vals["tot_ask"] = _int(rec[_BI["TOTAL_ASKP_RSQN"]])
    vals["tot_bid"] = _int(rec[_BI["TOTAL_BIDP_RSQN"]])
    vals["acml_vol"] = _int(rec[_BI["ACML_VOL"]])
    a, b = vals["ask_px1"], vals["bid_px1"]
    if a < 0 or b < 0 or (a == 0 and b == 0):
        raise ValueError(f"bad top-of-book ask1={a} bid1={b}")
    if a == 0 or b == 0:
        return sym, sec, vals, "one_sided"
    if rec[_BI["HOUR_CLS_CODE"]].strip() in ("", "0") and not a > b:
        raise ValueError(f"crossed book ask1={a} bid1={b}")
    return sym, sec, vals, "ok"


@dataclass
class Trade:
    symbol: str
    sec: int
    price: int
    qty: int
    side: str        # 'buy'|'sell'|'other'
    acml_vol: int


def flow_record(rec: list[str]) -> Trade:
    sym = _symbol(rec[_FI["MKSC_SHRN_ISCD"]])
    sec = _sec(rec[_FI["STCK_CNTG_HOUR"]])
    px = _int(rec[_FI["STCK_PRPR"]])
    qty = _int(rec[_FI["CNTG_VOL"]])
    if px <= 0 or qty < 0:
        raise ValueError(f"bad trade px={px} qty={qty}")
    d = rec[_FI["CCLD_DVSN"]].strip()
    if d not in ("1", "3", "5"):  # 컬럼 위치가 어긋나면 여기서 걸린다(체결 형식 미검증 — 이상 처리·원문 샘플)
        raise ValueError(f"bad CCLD_DVSN {d!r}")
    side = "buy" if d == "1" else "sell" if d == "5" else "other"
    return Trade(sym, sec, px, qty, side, _int(rec[_FI["ACML_VOL"]]))


# ── 1초 집계 ────────────────────────────────────────────────────────────────
@dataclass
class _BookState:
    sec: int
    vals: dict[str, int]
    n: int
    last_emitted: tuple | None = None
    last_sec: int | None = None


def _new_flow(sym: str, sec: int, px: int) -> dict[str, Any]:
    return {"symbol": sym, "sec": sec, **{c: 0 for c in FLOW_SUM_COLS},
            "first_px": px, "last_px": px, "high_px": px, "low_px": px, "acml_vol": 0}


def _add_trade(b: dict[str, Any], t: Trade) -> None:
    amt = t.price * t.qty
    b["n_trades"] += 1
    if t.side == "buy":
        b["buy_qty"] += t.qty
        b["buy_amt"] += amt
        if amt >= BIG_TRADE_AMT:
            b["big_buy_amt"] += amt
    elif t.side == "sell":
        b["sell_qty"] += t.qty
        b["sell_amt"] += amt
        if amt >= BIG_TRADE_AMT:
            b["big_sell_amt"] += amt
    else:
        b["other_qty"] += t.qty
    b["last_px"] = t.price
    b["high_px"] = max(b["high_px"], t.price)
    b["low_px"] = min(b["low_px"], t.price)
    b["acml_vol"] = t.acml_vol


@dataclass
class Aggregator:
    """종목별 1초 집계. 확정 행은 book_rows/flow_rows에 쌓이고 flush 때 비운다."""

    book_rows: list[dict[str, Any]] = field(default_factory=list)
    flow_rows: list[dict[str, Any]] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    _book: dict[str, _BookState] = field(default_factory=dict)
    _flow: dict[str, dict[str, Any]] = field(default_factory=dict)

    def _inc(self, key: str, n: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + n

    # 호가
    def add_book(self, sym: str, sec: int, vals: dict[str, int]) -> None:
        if sec < MIN_SEC:
            self._inc("book_pre0830")
            return
        st = self._book.get(sym)
        if st is None:
            self._book[sym] = _BookState(sec, vals, 1)
            return
        if st.vals is not None and sec == st.sec:
            st.vals, st.n = vals, st.n + 1
            return
        if sec < st.sec:  # 늦게 도착한 과거 초 호가 = 낡은 상태 → 버림
            self._inc("book_out_of_order")
            return
        self._emit_book(sym, st)
        st.sec, st.vals, st.n = sec, vals, 1

    def _emit_book(self, sym: str, st: _BookState) -> None:
        if st.vals is None:
            return
        key = tuple(st.vals[c] for c in BOOK_VALUE_COLS)
        if key != st.last_emitted or st.sec == st.last_sec:
            self.book_rows.append({"symbol": sym, "sec": st.sec, **st.vals, "n_updates": st.n})
            st.last_emitted = key
            st.last_sec = st.sec
        else:
            self._inc("book_unchanged_skipped")
        st.vals, st.n = None, 0  # type: ignore[assignment]

    # 체결
    def add_trade(self, t: Trade) -> None:
        if t.sec < MIN_SEC:
            self._inc("flow_pre0830")
            return
        b = self._flow.get(t.symbol)
        if b is not None and t.sec == b["sec"]:
            _add_trade(b, t)
            return
        if b is not None and t.sec < b["sec"]:
            # 늦게 온 과거 초 체결: 버리지 않고 단독 행으로 확정 → compact가 (symbol,sec)로 합산
            self._inc("flow_out_of_order")
            late = _new_flow(t.symbol, t.sec, t.price)
            _add_trade(late, t)
            self.flow_rows.append(late)
            return
        if b is not None:
            self.flow_rows.append(b)
        nb = _new_flow(t.symbol, t.sec, t.price)
        _add_trade(nb, t)
        self._flow[t.symbol] = nb

    def finalize_pending(self) -> None:
        """주기 flush·종료 시: 진행 중인 초를 확정. 같은 초에 메시지가 더 오면 같은 sec 행이 또 생기며
        compact가 (symbol,sec) 기준으로 합친다(호가=마지막 상태·n_updates 합, 체결=합산)."""
        for sym, st in self._book.items():
            self._emit_book(sym, st)
        for b in self._flow.values():
            self.flow_rows.append(b)
        self._flow.clear()

    def take_rows(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        book, flow = self.book_rows, self.flow_rows
        self.book_rows, self.flow_rows = [], []
        return book, flow


# ── 저장 ────────────────────────────────────────────────────────────────────
def day_dir(day: str) -> Path:
    return ROOT / day


def _pd():
    import pandas as pd
    return pd


def _frame(rows: list[dict[str, Any]], cols: list[str], dtypes: dict[str, str]):
    pd = _pd()
    df = pd.DataFrame(rows, columns=cols)
    return df.astype(dtypes)


def _write_parquet_atomic(df, path: Path, metadata: dict[str, str] | None = None,
                          compression: str = "zstd") -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pa.Table.from_pandas(df, preserve_index=False)
    if metadata:
        meta = dict(table.schema.metadata or {})
        meta.update({k.encode(): v.encode() for k, v in metadata.items()})
        table = table.replace_schema_metadata(meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    pq.write_table(table, tmp, compression=compression)
    os.replace(tmp, path)


_COMPACTED_KEY = "orderbook_compacted_parts"


def _compacted_parts(path: Path) -> list[str]:
    if not path.exists():
        return []
    import pyarrow.parquet as pq
    meta = pq.read_schema(path).metadata or {}
    raw = meta.get(_COMPACTED_KEY.encode())
    return json.loads(raw.decode()) if raw else []


def _part_files(d: Path, kind: str) -> list[Path]:
    return sorted(p for p in d.glob(f"{kind}_*.parquet"))


def write_part(day: str, hhmm: str, book_rows: list[dict[str, Any]],
               flow_rows: list[dict[str, Any]]) -> list[Path]:
    """10분 버퍼를 part 파일로(원자적). 같은 이름이 이미 있거나 이미 compact에 쓰였으면 _N 접미사."""
    d = day_dir(day)
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for kind, rows, cols, dt in (("book", book_rows, BOOK_COLS, BOOK_DTYPES),
                                 ("flow", flow_rows, FLOW_COLS, FLOW_DTYPES)):
        if not rows:
            continue
        used = set(_compacted_parts(d / f"{kind}.parquet"))
        name, k = f"{kind}_{hhmm}.parquet", 1
        while (d / name).exists() or name in used:
            name, k = f"{kind}_{hhmm}_{k}.parquet", k + 1
        p = d / name
        _write_parquet_atomic(_frame(rows, cols, dt), p, compression="snappy")
        out.append(p)
    return out


def merge_book(df):
    """(symbol,sec) 중복 → 마지막 상태 1행, n_updates 합. 입력 순서 = 도착 순서."""
    if df.empty:
        return df
    df = df.reset_index(drop=True)
    n = df.groupby(["symbol", "sec"], sort=False)["n_updates"].transform("sum")
    df = df.assign(n_updates=n.astype("int32"))
    df = df.drop_duplicates(["symbol", "sec"], keep="last")
    return df.sort_values(["symbol", "sec"], kind="stable").reset_index(drop=True)


def merge_flow(df):
    if df.empty:
        return df
    agg = {c: "sum" for c in FLOW_SUM_COLS}
    agg.update({"first_px": "first", "last_px": "last", "high_px": "max", "low_px": "min",
                "acml_vol": "max"})
    out = df.reset_index(drop=True).groupby(["symbol", "sec"], sort=False, as_index=False).agg(agg)
    out = out[FLOW_COLS].astype(FLOW_DTYPES)
    return out.sort_values(["symbol", "sec"], kind="stable").reset_index(drop=True)


def compact_day(day: str) -> dict[str, int]:
    """part들을 book.parquet/flow.parquet에 합치고 part 삭제. 멱등:
    합본 메타데이터에 이미 합친 part 이름을 기록 → rename 후 삭제 전에 죽어도 재실행 시 이중 합산 안 함."""
    pd = _pd()
    d = day_dir(day)
    result: dict[str, int] = {}
    if not d.exists():
        return result
    for kind, cols, dt, merge in (("book", BOOK_COLS, BOOK_DTYPES, merge_book),
                                  ("flow", FLOW_COLS, FLOW_DTYPES, merge_flow)):
        final = d / f"{kind}.parquet"
        done = _compacted_parts(final)
        parts = _part_files(d, kind)
        new_parts = [p for p in parts if p.name not in done]
        if not new_parts:
            for p in parts:  # 이미 합쳐진 잔여 part만 정리
                p.unlink(missing_ok=True)
            if final.exists():
                import pyarrow.parquet as pq
                result[kind] = pq.ParquetFile(final).metadata.num_rows
            continue
        frames = []
        if final.exists():
            frames.append(pd.read_parquet(final))
        frames += [pd.read_parquet(p) for p in new_parts]
        df = pd.concat([f[cols].astype(dt) for f in frames], ignore_index=True)
        df = merge(df)[cols].astype(dt)
        _write_parquet_atomic(df, final, {_COMPACTED_KEY: json.dumps(done + [p.name for p in new_parts])})
        for p in parts:
            p.unlink(missing_ok=True)
        result[kind] = len(df)
    return result


def dir_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) if root.exists() else 0


def disk_guard(root: Path | None = None, max_bytes: int | None = None,
               min_free: int | None = None, free_bytes: int | None = None,
               used_bytes: int | None = None) -> str | None:
    """중단해야 하면 사유 문자열, 아니면 None."""
    root = root or ROOT
    max_bytes = MAX_BYTES if max_bytes is None else max_bytes
    min_free = MIN_FREE_BYTES if min_free is None else min_free
    used = dir_bytes(root) if used_bytes is None else used_bytes
    if used >= max_bytes:
        return f"수집 용량 {used / 1e9:.2f}GB ≥ 상한 {max_bytes / 1e9:.2f}GB"
    if free_bytes is None:
        probe = root if root.exists() else root.parent
        while not probe.exists():
            probe = probe.parent
        free_bytes = shutil.disk_usage(probe).free
    if free_bytes < min_free:
        return f"여유공간 {free_bytes / 1e9:.2f}GB < {min_free / 1e9:.2f}GB"
    return None


def status() -> dict[str, Any]:
    import pyarrow.parquet as pq
    days: dict[str, Any] = {}
    if ROOT.exists():
        for d in sorted(p for p in ROOT.iterdir() if p.is_dir()):
            files = {}
            for f in sorted(d.iterdir()):
                if not f.is_file():
                    continue
                info: dict[str, Any] = {"mb": round(f.stat().st_size / 1e6, 2)}
                if f.suffix == ".parquet":
                    try:
                        info["rows"] = pq.ParquetFile(f).metadata.num_rows
                    except Exception as e:  # noqa: BLE001
                        info["error"] = str(e)[:80]
                files[f.name] = info
            days[d.name] = files
    return {"root": str(ROOT), "total_mb": round(dir_bytes(ROOT) / 1e6, 2), "days": days}


# ── 종목 선정 ───────────────────────────────────────────────────────────────
def select_symbols(today: str, n: int = N_SYMBOLS, min_close: float = MIN_CLOSE,
                   master: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """오늘(KST) 이전 날짜 중 최신 완료 거래일의 거래대금 상위 n 보통주(종가 ≥ min_close)."""
    master = master if master is not None else h.load_master()
    names = {m["symbol"]: m.get("name", "") for m in master}
    last: dict[str, tuple[str, float, float]] = {}
    for sym in names:
        df = h.read_daily(sym)
        if df is None or not len(df):
            continue
        df = df[df["date"].astype(str) < today]
        if not len(df):
            continue
        row = df.sort_values("date").iloc[-1]
        last[sym] = (str(row["date"]), float(row["close"] or 0), float(row["amount"] or 0))
    if not last:
        raise RuntimeError("일봉 데이터 없음 — collect_market_history 먼저 실행 필요")
    ref_day = max(v[0] for v in last.values())
    cands = [(amt, sym, close) for sym, (dt, close, amt) in last.items()
             if dt == ref_day and close >= min_close]
    cands.sort(key=lambda x: (-x[0], x[1]))
    picked = [{"symbol": s, "name": names.get(s, ""), "close": c, "amount": a} for a, s, c in cands[:n]]
    return {"day": today, "ref_day": ref_day, "symbols": picked}


def load_or_select_symbols(day: str) -> dict[str, Any]:
    p = day_dir(day) / "symbols.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    sel = select_symbols(day)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(".symbols.json.tmp")
    tmp.write_text(json.dumps(sel, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return sel


# ── 수집기 ──────────────────────────────────────────────────────────────────
def subscribe_message(approval_key: str, tr_id: str, symbol: str) -> str:
    return json.dumps({"header": {"approval_key": approval_key, "custtype": "P", "tr_type": "1",
                                  "content-type": "utf-8"},
                       "body": {"input": {"tr_id": tr_id, "tr_key": symbol}}})


class Collector:
    def __init__(self, day: str, symbols: list[str], now_fn: Callable[[], datetime] | None = None):
        self._started_hhmm = "0000"  # run()이 실제 시작 시각으로 갱신
        if len(symbols) * 2 > WS_SLOT_LIMIT:
            raise ValueError(f"구독 {len(symbols) * 2}슬롯 > {WS_SLOT_LIMIT}")
        self.day = day
        self.symbols = symbols
        self.now = now_fn or (lambda: datetime.now(KST))
        self.agg = Aggregator()
        self.data_msgs = 0
        self.records = {TR_BOOK: 0, TR_FLOW: 0}
        self.anomalies = {TR_BOOK: 0, TR_FLOW: 0}
        self.acks_ok = 0
        self.connects = 0
        self.connect_failures = 0
        self.stop_event = asyncio.Event()
        self.stop_reason = ""
        self._approval_key: str | None = None
        self._anomaly_logged = self._count_anomaly_lines()
        self.widths: dict[str, dict[int, int]] = {}  # TR별 관측 레코드 폭 분포(형식 변경 감지)

    # 상태·이상 기록
    def request_stop(self, reason: str) -> None:
        if not self.stop_event.is_set():
            self.stop_reason = reason
            self.stop_event.set()

    def _anomaly_path(self) -> Path:
        return day_dir(self.day) / "_anomaly.log"

    def _count_anomaly_lines(self) -> dict[str, int]:
        p = self._anomaly_path()
        out: dict[str, int] = {}
        if not p.exists():
            return out
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("#"):
                parts = line.split()
                if len(parts) >= 3:
                    out[parts[2]] = out.get(parts[2], 0) + 1
        return out

    def _anomaly(self, tr_id: str, reason: str, raw: str) -> None:
        self.anomalies[tr_id] = self.anomalies.get(tr_id, 0) + 1
        self._log_sample(tr_id, reason, raw, warn=True)

    def _log_sample(self, tr_id: str, reason: str, raw: str, warn: bool) -> None:
        if self._anomaly_logged.get(tr_id, 0) >= ANOMALY_MAX_PER_DAY:
            return
        self._anomaly_logged[tr_id] = self._anomaly_logged.get(tr_id, 0) + 1
        p = self._anomaly_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(f"# {self.now().strftime('%H:%M:%S')} {tr_id} {reason}\n{raw[:300]}\n")
        if warn:
            logger.warning("WARN: [Orderbook] 이상 레코드 %s %s", tr_id, reason)

    # 메시지 처리
    async def handle_message(self, raw: str | bytes, ws: Any = None) -> None:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        if raw[:1] in ("0", "1"):
            self._handle_data(raw)
            return
        try:
            msg = json.loads(raw)
        except ValueError:
            logger.warning("WARN: [Orderbook] 알 수 없는 메시지 %r", raw[:80])
            return
        if not isinstance(msg, dict):
            logger.warning("WARN: [Orderbook] 알 수 없는 JSON %r", raw[:80])
            return
        header = msg.get("header") or {}
        if header.get("tr_id") == "PINGPONG":
            if ws is not None:
                await ws.send(raw)
            return
        body = msg.get("body") or {}
        rt = str(body.get("rt_cd", ""))
        if rt == "0":
            self.acks_ok += 1
        else:  # approval_key·암호화 키(output) 는 로그 금지 — tr_id·종목·msg1만
            logger.warning("WARN: [Orderbook] 구독 응답 rt_cd=%s tr=%s key=%s msg=%s", rt,
                           header.get("tr_id"), header.get("tr_key"), body.get("msg1"))

    def _handle_data(self, raw: str) -> None:
        parsed = parse_data_message(raw)
        if parsed is None:
            return
        self.data_msgs += 1
        if parsed.width:
            wd = self.widths.setdefault(parsed.tr_id, {})
            if parsed.width not in wd:  # 새 폭 첫 관측 → 원문 샘플(형식 검증용, 경고 아님)
                self._log_sample(parsed.tr_id, f"sample width {parsed.width}", raw, warn=False)
                logger.info("INFO: [Orderbook] %s 레코드 폭 %d 첫 관측", parsed.tr_id, parsed.width)
            wd[parsed.width] = wd.get(parsed.width, 0) + 1
        if parsed.anomaly:
            self._anomaly(parsed.tr_id, parsed.anomaly, raw)
            return
        for rec in parsed.records:
            self.records[parsed.tr_id] += 1
            try:
                if parsed.tr_id == TR_BOOK:
                    sym, sec, vals, kind = book_record(rec)
                    if kind == "one_sided":
                        self.agg._inc("book_one_sided")
                    self.agg.add_book(sym, sec, vals)
                else:
                    self.agg.add_trade(flow_record(rec))
            except (ValueError, IndexError, OverflowError, TypeError) as e:
                self._anomaly(parsed.tr_id, str(e), "^".join(rec))

    # flush
    def flush(self, finalize: bool = True) -> list[Path]:
        if finalize:
            self.agg.finalize_pending()
        book, flow = self.agg.take_rows()
        try:
            paths = write_part(self.day, self.now().strftime("%H%M"), book, flow)
        except Exception:
            self.agg.book_rows[:0] = book  # 기록 실패 → 버퍼로 되돌려 다음 flush에 재시도
            self.agg.flow_rows[:0] = flow
            raise
        if paths:
            logger.info("SUCCESS: [Orderbook] part 기록 book=%d flow=%d 행 · 수신 data=%d 레코드=%s 이상=%s",
                        len(book), len(flow), self.data_msgs, self.records, self.anomalies)
        return paths

    # 네트워크
    async def _issue_approval(self) -> str:
        import httpx
        cfg = h.settings
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{cfg.KIS_DATA_URL}/oauth2/Approval",
                             json={"grant_type": "client_credentials", "appkey": cfg.KIS_DATA_APP_KEY,
                                   "secretkey": cfg.KIS_DATA_APP_SECRET})
        if r.status_code != 200:
            raise RuntimeError(f"approval HTTP {r.status_code}")  # 본문(키 포함 가능) 로그 금지
        key = (r.json() or {}).get("approval_key")
        if not key:
            raise RuntimeError("approval_key 없음")
        return str(key)

    async def _session(self) -> None:
        import websockets
        if self._approval_key is None:
            self._approval_key = await self._issue_approval()
        async with websockets.connect(WS_URL, ping_interval=None, max_size=2 ** 22) as ws:
            self.connects += 1
            for sym in self.symbols:
                for tr in (TR_BOOK, TR_FLOW):
                    await ws.send(subscribe_message(self._approval_key, tr, sym))
                    await asyncio.sleep(0.05)
            logger.info("SUCCESS: [Orderbook] 연결·구독 요청 %d종목×2 (연결 %d회째)", len(self.symbols),
                        self.connects)
            while not self.stop_event.is_set():
                raw = await asyncio.wait_for(ws.recv(), timeout=RECV_TIMEOUT_SEC)
                try:
                    await self.handle_message(raw, ws)
                except Exception as e:  # noqa: BLE001 — 메시지 1건 오류로 40슬롯 재구독하지 않는다
                    self._anomaly("unknown", f"{type(e).__name__}: {e}", str(raw)[:300])

    async def _ws_loop(self) -> None:
        backoff = 2.0
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.connect_failures += 1
                if "approval" in str(e):
                    self._approval_key = None
                logger.warning("WARN: [Orderbook] 연결 끊김/실패 %s: %s — %.0f초 후 재연결",
                               type(e).__name__, str(e)[:120], backoff)
            if time.monotonic() - started > 300:
                backoff = 2.0  # 오래 붙어 있었으면 백오프 초기화
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 60.0)

    async def _flusher(self) -> None:
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=FLUSH_SEC)
                return
            except asyncio.TimeoutError:
                pass
            try:
                self.flush()
            except Exception as e:  # noqa: BLE001 — 저장 실패가 수집 태스크를 죽이면 안 된다
                logger.error("FAIL: [Orderbook] part 기록 실패 %s: %s", type(e).__name__, str(e)[:160])
            reason = disk_guard()
            if reason:
                logger.error("FAIL: [Orderbook] 디스크 보호 중단 — %s", reason)
                self.request_stop("disk")

    async def _timekeeper(self) -> None:
        while not self.stop_event.is_set():
            hhmm = self.now().strftime("%H%M")
            if hhmm >= END_HHMM:
                self.request_stop("end_of_session")
            elif self._started_hhmm < HOLIDAY_CHECK_HHMM <= hhmm and self.data_msgs == 0:
                logger.warning("WARN: [Orderbook] %s까지 데이터 0건 — 휴장 추정(연결 %d회·실패 %d회) 종료",
                               HOLIDAY_CHECK_HHMM, self.connects, self.connect_failures)
                self.request_stop("holiday_suspected")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    async def run(self) -> str:
        """08:50 대기 → 수집 → 15:35/신호/디스크/휴장 시 flush+compact. 종료 사유 반환."""
        while self.now().strftime("%H%M") < START_HHMM and not self.stop_event.is_set():
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                pass
        tasks = []
        self._started_hhmm = self.now().strftime("%H%M")  # 장중 재시작은 휴장 판정 제외(검토 지적)
        if not self.stop_event.is_set():
            logger.info("START: [Orderbook] 수집 %s 종목 %d개", self.day, len(self.symbols))
            tasks = [asyncio.create_task(c()) for c in (self._ws_loop, self._flusher, self._timekeeper)]
            await self.stop_event.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            self.flush()
        except Exception as e:  # noqa: BLE001
            logger.error("FAIL: [Orderbook] 마지막 part 기록 실패 %s: %s", type(e).__name__, str(e)[:160])
        res = compact_day(self.day)
        logger.info("SUCCESS: [Orderbook] 종료(%s) compact=%s 수신 data=%d 레코드=%s 이상=%s ACK=%d 폭=%s 집계=%s",
                    self.stop_reason, res, self.data_msgs, self.records, self.anomalies, self.acks_ok,
                    self.widths, self.agg.counters)
        return self.stop_reason


def require_data_key() -> None:
    cfg = h.settings
    if not (cfg.KIS_DATA_APP_KEY and cfg.KIS_DATA_APP_SECRET and cfg.KIS_DATA_URL):
        raise RuntimeError("KIS_DATA_APP_KEY/SECRET/URL 미설정 — 실전 조회키 전용(모의키 대체 금지)")


def compact_pending_days(days: Iterable[str] | None = None) -> dict[str, dict[str, int]]:
    """part가 남은 날짜들 compact(이전 비정상 종료 정리)."""
    out = {}
    if not ROOT.exists():
        return out
    targets = days if days is not None else [d.name for d in ROOT.iterdir()
                                             if d.is_dir() and any(d.glob("*_*.parquet"))]
    for d in sorted(targets):
        out[d] = compact_day(d)
    return out

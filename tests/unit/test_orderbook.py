"""호가·체결 1초 집계 수집기(market_data.orderbook) — 네트워크 없음, tmp_path 격리."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

import pandas as pd
import pytest

import backend.services.market_data.history as h
import backend.services.market_data.orderbook as ob


@pytest.fixture(autouse=True)
def _tmp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "ROOT", tmp_path / "orderbook")
    monkeypatch.setattr(h, "ROOT", tmp_path / "market")
    return tmp_path


# ── 합성 레코드 ─────────────────────────────────────────────────────────────
def book_fields(sym="005930", t="090001", ask1=70100, bid1=70000, cls="0", acml=1000, qbase=10):
    f = {n: "0" for n in ob.BOOK_FIELDS}
    f.update(MKSC_SHRN_ISCD=sym, BSOP_HOUR=t, HOUR_CLS_CODE=cls, ACML_VOL=str(acml))
    for i in range(1, 11):
        f[f"ASKP{i}"] = str(ask1 + (i - 1) * 100)
        f[f"BIDP{i}"] = str(max(bid1 - (i - 1) * 100, 0) if bid1 else 0)
        f[f"ASKP_RSQN{i}"] = str(qbase + i)
        f[f"BIDP_RSQN{i}"] = str(qbase * 2 + i)
    f["TOTAL_ASKP_RSQN"] = "5555"
    f["TOTAL_BIDP_RSQN"] = "6666"
    f["ANTC_CNPR"] = "99999"  # 저장 안 하는 필드 — 위치 혼동 검출용
    return [f[n] for n in ob.BOOK_FIELDS]


def flow_fields(sym="005930", t="090001", px=70000, qty=10, dvsn="1", acml=500):
    f = {n: "0" for n in ob.FLOW_FIELDS}
    f.update(MKSC_SHRN_ISCD=sym, STCK_CNTG_HOUR=t, STCK_PRPR=str(px), CNTG_VOL=str(qty),
             CCLD_DVSN=dvsn, ACML_VOL=str(acml), ASKP1=str(px + 100), BIDP1=str(px), STCK_OPRC="1")
    return [f[n] for n in ob.FLOW_FIELDS]


def msg(tr, records):
    return f"0|{tr}|{len(records):03d}|" + "^".join("^".join(r) for r in records)


# ── 파싱 ────────────────────────────────────────────────────────────────────
def test_book_field_positions():
    p = ob.parse_data_message(msg(ob.TR_BOOK, [book_fields()]))
    assert p.anomaly is None and len(p.records) == 1
    sym, sec, v, kind = ob.book_record(p.records[0])
    assert (sym, sec, kind) == ("005930", 90001, "ok")
    assert v["ask_px1"] == 70100 and v["ask_px10"] == 71000
    assert v["bid_px1"] == 70000 and v["bid_px10"] == 69100
    assert v["ask_qty1"] == 11 and v["ask_qty10"] == 20
    assert v["bid_qty1"] == 21 and v["bid_qty10"] == 30
    assert (v["tot_ask"], v["tot_bid"], v["acml_vol"]) == (5555, 6666, 1000)
    assert 99999 not in v.values()
    # 인덱스 직접 확인(명세 순서)
    assert ob.BOOK_FIELDS.index("ASKP1") == 3 and ob.BOOK_FIELDS.index("BIDP1") == 13
    assert ob.BOOK_FIELDS.index("ASKP_RSQN1") == 23 and ob.BOOK_FIELDS.index("BIDP_RSQN1") == 33
    assert ob.BOOK_FIELDS.index("TOTAL_ASKP_RSQN") == 43 and ob.BOOK_FIELDS.index("ACML_VOL") == 53


def test_book_multi_record():
    p = ob.parse_data_message(msg(ob.TR_BOOK, [book_fields("005930"), book_fields("000660", ask1=200500,
                                                                                    bid1=200000)]))
    assert p.anomaly is None and len(p.records) == 2
    assert ob.book_record(p.records[1])[0] == "000660"
    assert ob.book_record(p.records[1])[2]["ask_px1"] == 200500


def test_field_count_mismatch_is_anomaly(_tmp_root):
    rec = book_fields()[:-1]  # 58필드
    raw = f"0|{ob.TR_BOOK}|001|" + "^".join(rec)
    p = ob.parse_data_message(raw)
    assert p.anomaly and p.records == []
    # COUNT 불일치도 이상
    raw2 = f"0|{ob.TR_BOOK}|002|" + "^".join(book_fields())
    assert ob.parse_data_message(raw2).anomaly
    col = ob.Collector("20261008", ["005930"], now_fn=lambda: datetime(2026, 10, 8, 9, 0, 1))
    for _ in range(25):
        asyncio.run(col.handle_message(raw))
    assert col.anomalies[ob.TR_BOOK] == 25
    assert col.agg.book_rows == [] and not col.agg._book
    log = (ob.ROOT / "20261008" / "_anomaly.log").read_text(encoding="utf-8")
    assert sum(line.startswith("# ") for line in log.splitlines()) == ob.ANOMALY_MAX_PER_DAY
    assert all(len(line) <= 300 for line in log.splitlines() if not line.startswith("#"))


def test_book_validation():
    with pytest.raises(ValueError):
        ob.book_record(book_fields(ask1=70000, bid1=70000))           # 교차(연속매매)
    with pytest.raises(ValueError):
        ob.book_record(book_fields(ask1=0, bid1=0))
    assert ob.book_record(book_fields(ask1=70000, bid1=70000, cls="B"))[3] == "ok"   # 동시호가 교차 허용
    assert ob.book_record(book_fields(ask1=0, bid1=70000))[3] == "one_sided"         # 상한가


def test_bad_book_counts_anomaly_but_keeps_other_records():
    col = ob.Collector("20261008", ["005930"], now_fn=lambda: datetime(2026, 10, 8, 9, 0, 1))
    raw = msg(ob.TR_BOOK, [book_fields(ask1=70000, bid1=70100), book_fields("000660")])
    asyncio.run(col.handle_message(raw))
    assert col.anomalies[ob.TR_BOOK] == 1 and "000660" in col.agg._book


def test_flow_multi_record_and_sides():
    recs = [flow_fields(px=70000, qty=10, dvsn="1"), flow_fields(px=70100, qty=500, dvsn="1"),  # 35.05M 큰매수
            flow_fields(px=69900, qty=20, dvsn="5"), flow_fields(px=69800, qty=1000, dvsn="5"),  # 69.8M 큰매도
            flow_fields(px=70000, qty=7, dvsn="3", acml=9999)]
    p = ob.parse_data_message(msg(ob.TR_FLOW, recs))
    assert p.anomaly is None and len(p.records) == 5
    t = ob.flow_record(p.records[1])
    assert (t.symbol, t.sec, t.price, t.qty, t.side) == ("005930", 90001, 70100, 500, "buy")
    agg = ob.Aggregator()
    for r in p.records:
        agg.add_trade(ob.flow_record(r))
    agg.finalize_pending()
    (row,) = agg.flow_rows
    assert row["n_trades"] == 5
    assert (row["buy_qty"], row["sell_qty"], row["other_qty"]) == (510, 1020, 7)
    assert row["buy_amt"] == 70000 * 10 + 70100 * 500
    assert row["sell_amt"] == 69900 * 20 + 69800 * 1000
    assert row["big_buy_amt"] == 70100 * 500 and row["big_sell_amt"] == 69800 * 1000
    assert (row["first_px"], row["last_px"], row["high_px"], row["low_px"]) == (70000, 70000, 70100, 69800)
    assert row["acml_vol"] == 9999


def test_flow_seconds_split_and_late_trade():
    agg = ob.Aggregator()
    agg.add_trade(ob.Trade("A00001", 90001, 100, 1, "buy", 1))
    agg.add_trade(ob.Trade("A00001", 90002, 101, 2, "sell", 3))
    agg.add_trade(ob.Trade("A00001", 90001, 99, 4, "buy", 3))   # 늦게 온 과거 초
    agg.add_trade(ob.Trade("A00001", 82959, 99, 4, "buy", 3))   # 08:30 이전 → 버림
    agg.finalize_pending()
    df = ob.merge_flow(ob._frame(agg.flow_rows, ob.FLOW_COLS, ob.FLOW_DTYPES))
    assert list(df["sec"]) == [90001, 90002]
    assert df.loc[0, "buy_qty"] == 5 and df.loc[0, "n_trades"] == 2 and df.loc[0, "low_px"] == 99


# ── 1초 집계(호가) ──────────────────────────────────────────────────────────
def _bv(**kw):
    return ob.book_record(book_fields(**kw))[2]


def test_book_last_state_per_second_and_skip_unchanged():
    agg = ob.Aggregator()
    agg.add_book("005930", 90001, _bv(qbase=10))
    agg.add_book("005930", 90001, _bv(qbase=11))
    agg.add_book("005930", 90001, _bv(qbase=12))      # 90001 마지막 상태
    agg.add_book("005930", 90002, _bv(qbase=12))      # 값 동일 → 행 생략
    agg.add_book("005930", 90005, _bv(qbase=13))      # 90003~04 메시지 없음 → 행 없음
    agg.add_book("005930", 90004, _bv(qbase=99))      # 과거 초 → 버림
    agg.finalize_pending()
    rows = agg.book_rows
    assert [r["sec"] for r in rows] == [90001, 90005]
    assert rows[0]["n_updates"] == 3 and rows[0]["ask_qty1"] == 13
    assert rows[1]["ask_qty1"] == 14
    assert agg.counters["book_unchanged_skipped"] == 1 and agg.counters["book_out_of_order"] == 1


def test_book_symbols_independent_and_pre0830_dropped():
    agg = ob.Aggregator()
    agg.add_book("A00001", 90001, _bv(qbase=1))
    agg.add_book("B00001", 90001, _bv(qbase=2))
    agg.add_book("A00001", 82959, _bv(qbase=3))
    agg.finalize_pending()
    assert sorted(r["symbol"] for r in agg.book_rows) == ["A00001", "B00001"]
    assert agg.counters["book_pre0830"] == 1


def test_premarket_kept():
    agg = ob.Aggregator()
    agg.add_book("A00001", 84500, _bv(qbase=1, cls="B"))
    agg.add_book("A00001", 153100, _bv(qbase=2, cls="A"))
    agg.finalize_pending()
    assert [r["sec"] for r in agg.book_rows] == [84500, 153100]


# ── part · compact ──────────────────────────────────────────────────────────
def _collect_rows(agg_steps):
    agg = ob.Aggregator()
    for sym, sec, q in agg_steps:
        agg.add_book(sym, sec, _bv(qbase=q))
        agg.add_trade(ob.Trade(sym, sec, 1000, q, "buy", q))
    agg.finalize_pending()
    return agg.take_rows()


def test_part_compact_idempotent(_tmp_root):
    day = "20261008"
    b1, f1 = _collect_rows([("A00001", 90001, 1), ("A00001", 90002, 2), ("B00001", 90001, 3)])
    b2, f2 = _collect_rows([("A00001", 90002, 5), ("A00001", 90003, 6)])  # 90002 flush 경계 중복
    ob.write_part(day, "0910", b1, f1)
    ob.write_part(day, "0920", b2, f2)
    d = ob.ROOT / day
    assert sorted(p.name for p in d.iterdir()) == ["book_0910.parquet", "book_0920.parquet",
                                                    "flow_0910.parquet", "flow_0920.parquet"]
    res = ob.compact_day(day)
    assert sorted(p.name for p in d.iterdir()) == ["book.parquet", "flow.parquet"]
    book = pd.read_parquet(d / "book.parquet")
    flow = pd.read_parquet(d / "flow.parquet")
    assert res == {"book": 4, "flow": 4}
    assert list(zip(book.symbol, book.sec)) == [("A00001", 90001), ("A00001", 90002), ("A00001", 90003),
                                                 ("B00001", 90001)]
    r = book[(book.symbol == "A00001") & (book.sec == 90002)].iloc[0]
    assert r.ask_qty1 == 6 and r.n_updates == 2          # 마지막 상태 + n_updates 합
    fr = flow[(flow.symbol == "A00001") & (flow.sec == 90002)].iloc[0]
    assert fr.buy_qty == 7 and fr.n_trades == 2
    assert str(book["ask_px1"].dtype) == "int32" and str(book["tot_ask"].dtype) == "int64"
    import pyarrow.parquet as pq
    assert pq.ParquetFile(d / "book.parquet").metadata.row_group(0).column(0).compression == "ZSTD"

    # 재compact(변화 없음) 멱등
    assert ob.compact_day(day) == res
    pd.testing.assert_frame_equal(pd.read_parquet(d / "book.parquet"), book)

    # 합본 rename 후 part 삭제 전에 죽은 상황: 이미 합친 part가 남아도 이중 합산 없음
    ob._write_parquet_atomic(ob._frame(f2, ob.FLOW_COLS, ob.FLOW_DTYPES), d / "flow_0920.parquet")
    ob.compact_day(day)
    pd.testing.assert_frame_equal(pd.read_parquet(d / "flow.parquet"), flow)
    assert not (d / "flow_0920.parquet").exists()

    # 재시작 후 같은 HHMM part — 이름 충돌 회피 + 기존 합본과 합침
    b3, f3 = _collect_rows([("A00001", 90003, 9)])
    paths = ob.write_part(day, "0920", b3, f3)
    assert [p.name for p in paths] == ["book_0920_1.parquet", "flow_0920_1.parquet"]
    ob.compact_day(day)
    flow2 = pd.read_parquet(d / "flow.parquet")
    assert flow2[(flow2.symbol == "A00001") & (flow2.sec == 90003)].iloc[0].buy_qty == 6 + 9


def test_atomic_write_leaves_no_tmp(_tmp_root, monkeypatch):
    import pyarrow.parquet as pq
    day = "20261008"
    b, f = _collect_rows([("A00001", 90001, 1)])
    ob.write_part(day, "0910", b, f)
    assert not list((ob.ROOT / day).glob(".*tmp"))

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(pq, "write_table", boom)
    with pytest.raises(OSError):
        ob.write_part(day, "0920", b, f)
    assert not (ob.ROOT / day / "book_0920.parquet").exists()   # 반쪽 파일 노출 없음


def test_collector_flush_writes_part(_tmp_root):
    col = ob.Collector("20261008", ["005930"], now_fn=lambda: datetime(2026, 10, 8, 9, 10, 0))
    asyncio.run(col.handle_message(msg(ob.TR_BOOK, [book_fields(t="090001"), book_fields(t="090001", qbase=20)])))
    asyncio.run(col.handle_message(msg(ob.TR_FLOW, [flow_fields(), flow_fields(t="090002")])))
    paths = col.flush()
    assert sorted(p.name for p in paths) == ["book_0910.parquet", "flow_0910.parquet"]
    book = pd.read_parquet(paths[0])
    assert len(book) == 1 and book.n_updates[0] == 2
    assert col.records == {ob.TR_BOOK: 2, ob.TR_FLOW: 2} and col.data_msgs == 2


def test_pingpong_echo_and_ack():
    class WS:
        def __init__(self):
            self.sent = []

        async def send(self, m):
            self.sent.append(m)

    ws = WS()
    col = ob.Collector("20261008", ["005930"])
    ping = json.dumps({"header": {"tr_id": "PINGPONG", "datetime": "20261008090000"}})
    asyncio.run(col.handle_message(ping, ws))
    assert ws.sent == [ping]
    ack = json.dumps({"header": {"tr_id": ob.TR_BOOK, "tr_key": "005930"},
                      "body": {"rt_cd": "0", "msg1": "SUBSCRIBE SUCCESS"}})
    asyncio.run(col.handle_message(ack, ws))
    assert col.acks_ok == 1 and col.data_msgs == 0


def test_slot_limit():
    with pytest.raises(ValueError):
        ob.Collector("20261008", [f"{i:06d}" for i in range(21)])


# ── 디스크 보호 ─────────────────────────────────────────────────────────────
def test_disk_guard(_tmp_root):
    root = ob.ROOT
    root.mkdir(parents=True)
    (root / "x.bin").write_bytes(b"0" * 1000)
    gb = 1024 ** 3
    assert ob.disk_guard(root, max_bytes=10_000, min_free=5 * gb, free_bytes=100 * gb) is None
    assert "상한" in ob.disk_guard(root, max_bytes=1000, min_free=5 * gb, free_bytes=100 * gb)
    assert "여유공간" in ob.disk_guard(root, max_bytes=10_000, min_free=5 * gb, free_bytes=4 * gb)
    assert ob.disk_guard(used_bytes=ob.MAX_BYTES, free_bytes=100 * gb)
    assert ob.disk_guard(used_bytes=0, free_bytes=100 * gb) is None


# ── 종목 선정 ───────────────────────────────────────────────────────────────
def _write_daily(sym, rows):
    p = h.daily_path(sym)
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=h.DAILY_COLS).to_parquet(p, index=False)


def test_select_symbols(_tmp_root):
    master = []
    for i in range(25):
        sym = f"{i:05d}0"
        master.append({"symbol": sym, "name": f"S{i}"})
        # 어제(1007) 거래대금 = i, 오늘(1008, 장중 미완성) 거래대금은 역순으로 크게
        _write_daily(sym, [["20261006", 0, 0, 0, 10000, 0, 1e9 * (25 - i)],
                           ["20261007", 0, 0, 0, 10000, 0, 1e9 * i],
                           ["20261008", 0, 0, 0, 10000, 0, 1e12 * (25 - i)]])
    # 종가 5천 미만은 제외(거래대금 최대라도)
    master.append({"symbol": "999990", "name": "PENNY"})
    _write_daily("999990", [["20261007", 0, 0, 0, 4990, 0, 1e15]])
    # 거래정지로 기준일 데이터 없는 종목은 제외
    master.append({"symbol": "888880", "name": "STALE"})
    _write_daily("888880", [["20261006", 0, 0, 0, 50000, 0, 1e15]])
    sel = ob.select_symbols("20261008", master=master)
    syms = [s["symbol"] for s in sel["symbols"]]
    assert sel["ref_day"] == "20261007"
    assert len(syms) == 20
    assert syms[0] == "000240" and syms[-1] == "000050"   # 거래대금 24..5
    assert "999990" not in syms and "888880" not in syms


def test_load_or_select_symbols_reuses_file(_tmp_root, monkeypatch):
    calls = []

    def fake_select(day):
        calls.append(day)
        return {"day": day, "ref_day": "20261007", "symbols": [{"symbol": "005930"}]}

    monkeypatch.setattr(ob, "select_symbols", fake_select)
    a = ob.load_or_select_symbols("20261008")
    b = ob.load_or_select_symbols("20261008")
    assert a == b and calls == ["20261008"]
    assert (ob.ROOT / "20261008" / "symbols.json").exists()


def test_require_data_key(monkeypatch):
    monkeypatch.setattr(h.settings, "KIS_DATA_APP_KEY", "", raising=False)
    with pytest.raises(RuntimeError):
        ob.require_data_key()


def test_status(_tmp_root):
    b, f = _collect_rows([("A00001", 90001, 1)])
    ob.write_part("20261008", "0910", b, f)
    ob.compact_day("20261008")
    st = ob.status()
    assert st["days"]["20261008"]["book.parquet"]["rows"] == 1


# ---- 독립 검토 반영 회귀 테스트 (2026-10-07) ----
def test_review_restart_after_0915_is_not_holiday():
    """장중(10:00) 재시작 직후 데이터 0건이어도 '휴장 추정'으로 종료하지 않는다."""
    import asyncio
    from datetime import datetime
    from backend.services.market_data import orderbook as ob
    c = ob.Collector("20261008", ["005930"], now_fn=lambda: datetime(2026, 10, 8, 10, 0, tzinfo=ob.KST))
    c._started_hhmm = "1000"

    async def go():
        t = asyncio.create_task(c._timekeeper())
        await asyncio.sleep(1.5)
        c.request_stop("test")
        await t
    asyncio.run(go())
    assert c.stop_reason == "test"


def test_review_flush_failure_restores_rows(monkeypatch):
    from backend.services.market_data import orderbook as ob
    c = ob.Collector("20261008", ["005930"])
    c.agg.flow_rows.append({"symbol": "005930", "sec": 90000})
    monkeypatch.setattr(ob, "write_part", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    try:
        c.flush(finalize=False)
    except OSError:
        pass
    assert len(c.agg.flow_rows) == 1  # 버려지지 않고 다음 flush 재시도 대상


def test_review_split_second_keeps_update_count():
    """flush가 같은 초를 둘로 나눠도 값이 같은 뒷부분 행을 버리지 않아 n_updates 합이 보존된다."""
    from backend.services.market_data import orderbook as ob
    agg = ob.Aggregator()
    vals = {c: 1 for c in ob.BOOK_VALUE_COLS}
    agg.add_book("005930", 90001, dict(vals)); agg.add_book("005930", 90001, dict(vals))
    agg.finalize_pending()
    agg.add_book("005930", 90001, dict(vals))
    agg.finalize_pending()
    import pandas as pd
    df = ob.merge_book(pd.DataFrame(agg.book_rows))
    assert int(df.n_updates.iloc[0]) == 3


# ---- 2026-10-08 첫 실데이터: H0STASP0 레코드 폭 63(문서 59) ----
REAL_ASP_20261008 = ("0|H0STASP0|001|005930^085010^B^271500^272000^272500^0^0^0^0^0^0^0^271000^270500^270000^0^0^0^0^0^0^0"
                     "^1464^672^583^0^0^0^0^0^0^0^8448^716^11470^0^0^0^0^0^0^0^2719^20634^0^35077^271500^55612^55612^3000^2"
                     "^1.12^61^-7^1^0^-752^0^0^0^0^5")


def test_real_asp_width_63_parses_documented_prefix():
    from backend.services.market_data import orderbook as ob
    p = ob.parse_data_message(REAL_ASP_20261008)
    assert p.anomaly is None and p.width == 63 and len(p.records) == 1
    sym, sec, vals, kind = ob.book_record(p.records[0])
    assert sym == "005930" and sec == 85010
    assert vals["ask_px1"] == 271500 and vals["ask_px3"] == 272500 and vals["bid_px1"] == 271000
    assert vals["ask_qty1"] == 1464 and vals["bid_qty3"] == 11470
    assert vals["tot_ask"] == 2719 and vals["tot_bid"] == 20634


def test_wider_multi_record_split_by_count():
    from backend.services.market_data import orderbook as ob
    body = REAL_ASP_20261008.split("|", 3)[3]
    raw = "0|H0STASP0|002|" + body + "^" + body.replace("005930", "000660")
    p = ob.parse_data_message(raw)
    assert p.anomaly is None and [r[0] for r in p.records] == ["005930", "000660"]


def test_narrower_than_documented_is_anomaly():
    from backend.services.market_data import orderbook as ob
    p = ob.parse_data_message("0|H0STASP0|001|" + "^".join(["1"] * 40))
    assert p.anomaly and "width" in p.anomaly

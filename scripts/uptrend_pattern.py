#!/usr/bin/env python3
"""상승장 필승패턴 탐색 — look-ahead 없는 실전 규칙 backtest (레짐별 승률·기대값).

오라클(oracle_backtest.py)이 밝힌 "개장 눌림(VWAP 아래)+빠른 청산"을 실제로 거래 가능한
규칙으로 구현해, 진입 5종 × 청산 4종을 과거 intraday_bars에 적용하고 레짐(상승/보합/하락)별
승률·평균손익·기대값을 측정한다. 추측이 아니라 숫자로 '상승장에 이기는 조합'을 찾는다.

- 진입: 09:05~지정시각 창에서 규칙 첫 충족 바에 close 매수(1종목-1일 1회). look-ahead 없음.
- 청산: 이후 바를 전진하며 TP/SL/트레일/시간 중 먼저 닿는 것. 같은 바 TP·SL 동시면 SL 우선(보수적).
- 비용: 왕복 0.25%(수수료+세금+슬리피지) 차감.
- 커버리지: 첫 바 ≤09:30 & 마지막 바 ≥14:00(청산 관측 보장). 우리는 승자를 일찍 팔아 바가 잘리는
  편향이 있어 종일커버 집합은 패자 쪽으로 기운다 → 그럼에도 이기는 패턴이면 강건.

읽기 전용. 사용: python scripts/uptrend_pattern.py [--start ..] [--end ..]
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "stock_trading_bot.sqlite3"
ROUND_TRIP_COST = 0.25   # % 왕복 비용
OPEN_BY, CLOSE_AFTER = "0930", "1400"


def _conn():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def regimes(conn, start, end):
    rows = conn.execute(
        """WITH k AS (SELECT substr(captured_at,1,10) d, change_rate,
             ROW_NUMBER() OVER (PARTITION BY substr(captured_at,1,10) ORDER BY captured_at DESC) rn
             FROM market_snapshots WHERE symbol='KOSPI')
           SELECT d, change_rate FROM k WHERE rn=1 AND d BETWEEN ? AND ?""",
        (start, end),
    ).fetchall()
    out = {}
    for r in rows:
        cr = r["change_rate"] or 0
        out[r["d"]] = ("상승" if cr >= 1.0 else "하락" if cr <= -1.0 else "보합", cr)
    return out


def load_minute_bars(conn, date, sym):
    rows = conn.execute(
        "SELECT bar_ts, open, high, low, close, volume FROM intraday_bars "
        "WHERE trade_date=? AND symbol=? ORDER BY bar_ts, id", (date, sym)).fetchall()
    by_ts = {r["bar_ts"]: r for r in rows}
    mins = {}
    for ts in sorted(by_ts):
        r = by_ts[ts]
        c = float(r["close"] or 0)
        if c <= 0:
            continue
        m = str(ts)[:4]
        b = mins.get(m)
        v = float(r["volume"] or 0)
        if b is None:
            mins[m] = {"m": m, "o": float(r["open"] or c), "h": float(r["high"] or c),
                       "l": float(r["low"] or c), "c": c, "v": v}
        else:
            b["h"] = max(b["h"], float(r["high"] or c)); b["l"] = min(b["l"], float(r["low"] or c))
            b["c"] = c; b["v"] += v
    return [mins[m] for m in sorted(mins)]


def covered(bars):
    return len(bars) >= 100 and bars[0]["m"] <= OPEN_BY and bars[-1]["m"] >= CLOSE_AFTER


def with_features(bars):
    """각 바까지의 VWAP·시가대비·평균거래량 부착(look-ahead 없음)."""
    day_open = bars[0]["o"]
    cum_pv = cum_v = 0.0
    for i, b in enumerate(bars):
        cum_pv += b["c"] * b["v"]; cum_v += b["v"]
        b["vwap"] = cum_pv / cum_v if cum_v > 0 else b["c"]
        b["cfo"] = (b["c"] / day_open - 1) * 100 if day_open else 0
        b["vwap_dist"] = (b["c"] / b["vwap"] - 1) * 100 if b["vwap"] else 0
        b["avg_v"] = cum_v / (i + 1)
        b["vol_surge"] = b["v"] / b["avg_v"] if b["avg_v"] else 0
    return bars


# ── 진입 규칙: (name, window_end, trigger(prev_bar, cur_bar)->bool)
def _entry_rules():
    return {
        "E1 개장VWAP눌림(-1%)": ("1000", lambda p, b: b["vwap_dist"] <= -1.0),
        "E2 깊은눌림(-2%)":     ("1030", lambda p, b: b["vwap_dist"] <= -2.0),
        "E3 눌림후VWAP회복":    ("1030", lambda p, b: p is not None and p["vwap_dist"] < 0 <= b["vwap_dist"]),
        "E4 추격(cfo≥+4)[대조]": ("1100", lambda p, b: b["cfo"] >= 4.0),
        "E5 현행눌림(cfo1.5~4·vol2)[대조]": ("1100", lambda p, b: 1.5 <= b["cfo"] <= 4.0 and b["vol_surge"] >= 2.0),
        # 추세지속(상승장 가설): 강한 종목을 얕은 눌림/VWAP 근처에서
        "E6 강세근접VWAP(cfo>0·VWAP0~1%위)": ("1030", lambda p, b: b["cfo"] > 0 and 0 <= b["vwap_dist"] <= 1.0),
        "E7 강세눌림후회복(cfo>+1·VWAP재상향)": ("1030", lambda p, b: b["cfo"] > 1.0 and p is not None and p["vwap_dist"] < 0 <= b["vwap_dist"]),
        "E8 개장강세유지(cfo>+2·VWAP위)": ("0945", lambda p, b: b["cfo"] > 2.0 and b["vwap_dist"] > 0),
        # 포착 레버: 밴드 확대(신호 수↑, 리스크 불변) — 승률 유지되나 검증
        "E9 강세밴드확대(cfo>0·VWAP-0.5~1.5%)": ("1100", lambda p, b: b["cfo"] > 0 and -0.5 <= b["vwap_dist"] <= 1.5),
        # 라이브 굶주림 해결 후보: 강세필터 유지 + 넓은 밴드(눌림 아래까지) — 거래는 하되 laggard(cfo<0) 회피
        "S1 강세+눌림아래(cfo>0·VWAP-2~0)": ("1100", lambda p, b: b["cfo"] > 0 and -2.0 <= b["vwap_dist"] <= 0.0),
        "S2 강세+와이드(cfo>0·VWAP-3~+1)": ("1100", lambda p, b: b["cfo"] > 0 and -3.0 <= b["vwap_dist"] <= 1.0),
        "S3 강세만(cfo>0·VWAP-5~+1)": ("1100", lambda p, b: b["cfo"] > 0 and -5.0 <= b["vwap_dist"] <= 1.0),
    }


def _find_entry(bars, win_end, trig):
    prev = None
    for i, b in enumerate(bars):
        if b["m"] > win_end:
            break
        if b["m"] < "0906":
            prev = b; continue
        if trig(prev, b):
            return i
        prev = b
    return None


# ── 청산 규칙: 진입 idx 이후 전진 시뮬. 반환 return%(비용 전)
def _exit(bars, ei, mode):
    entry = bars[ei]["c"]
    peak = entry
    for j in range(ei + 1, len(bars)):
        b = bars[j]
        peak = max(peak, b["h"])
        lo_ret = (b["l"] / entry - 1) * 100
        hi_ret = (b["h"] / entry - 1) * 100
        if mode == "Xa TP3/SL3":
            if lo_ret <= -3: return -3.0
            if hi_ret >= 3: return 3.0
        elif mode == "Xb TP2/SL2":
            if lo_ret <= -2: return -2.0
            if hi_ret >= 2: return 2.0
        elif mode == "Xc 트레일(발동+2·폭1.5)":
            if (peak / entry - 1) * 100 >= 2.0:
                trail = peak * (1 - 0.015)
                if b["l"] <= trail: return (trail / entry - 1) * 100
            if lo_ret <= -3: return -3.0
        elif mode == "Xe TP5/SL3":
            if lo_ret <= -3: return -3.0
            if hi_ret >= 5: return 5.0
        elif mode == "Xf 트레일(발동+3·폭2)":
            if (peak / entry - 1) * 100 >= 3.0:
                trail = peak * (1 - 0.02)
                if b["l"] <= trail: return (trail / entry - 1) * 100
            if lo_ret <= -3: return -3.0
        elif mode == "Xg 추세라이딩(발동+1.5·폭2.5·무캡)":
            # 수익 상한 없음 — 강한 추세를 끝까지. 시간정지 없이 14:50까지
            if (peak / entry - 1) * 100 >= 1.5:
                trail = peak * (1 - 0.025)
                if b["l"] <= trail: return (trail / entry - 1) * 100
            if lo_ret <= -3: return -3.0
            if b["m"] >= "1450":
                return (b["c"] / entry - 1) * 100
            continue  # 시간정지(1330) 건너뜀
        elif mode == "Xd 종가보유[대조]":
            pass
        # 시간정지 13:30
        if mode != "Xd 종가보유[대조]" and b["m"] >= "1330":
            return (b["c"] / entry - 1) * 100
    return (bars[-1]["c"] / entry - 1) * 100


def _exit_partial(bars, ei):
    """분할익절+러너: 60%는 +2%에서 확정, 40%는 러너(고점-2.5% 트레일·무캡). 둘 다 하드손절-3%.
    반환: (blended_return%, exit_bar_index) — 자본이 완전히 빠지는 시점(러너 청산)."""
    entry = bars[ei]["c"]
    peak = entry
    TP1, STOP, TRAIL = 2.0, -3.0, 0.025
    leg1 = None; leg2 = None; leg2_xi = len(bars) - 1
    for j in range(ei + 1, len(bars)):
        b = bars[j]; peak = max(peak, b["h"])
        lo = (b["l"] / entry - 1) * 100
        hi = (b["h"] / entry - 1) * 100
        if lo <= STOP:                       # 하드손절 — 두 다리 동시 -3
            if leg1 is None: leg1 = STOP
            leg2 = STOP; leg2_xi = j; break
        if leg1 is None and hi >= TP1:       # 1다리 +2% 확정
            leg1 = TP1
        if leg1 is not None and leg2 is None:  # 러너 트레일(+2 발동 후)
            if (peak / entry - 1) * 100 >= TP1:
                trail = peak * (1 - TRAIL)
                if b["l"] <= trail:
                    leg2 = (trail / entry - 1) * 100; leg2_xi = j
        if b["m"] >= "1450":                 # 종료 임박 — 남은 다리 종가청산
            if leg1 is None: leg1 = (b["c"] / entry - 1) * 100
            if leg2 is None: leg2 = (b["c"] / entry - 1) * 100
            leg2_xi = j; break
    if leg1 is None: leg1 = (bars[-1]["c"] / entry - 1) * 100
    if leg2 is None: leg2 = (bars[-1]["c"] / entry - 1) * 100
    return 0.6 * leg1 + 0.4 * leg2, leg2_xi


def _exit_with_time(bars, ei, mode):
    """단일다리 청산 + 청산 bar index 반환(포트폴리오 재활용 시뮬용)."""
    entry = bars[ei]["c"]; peak = entry
    for j in range(ei + 1, len(bars)):
        b = bars[j]; peak = max(peak, b["h"])
        lo = (b["l"] / entry - 1) * 100; hi = (b["h"] / entry - 1) * 100
        if mode == "Xc 트레일(발동+2·폭1.5)":
            if (peak / entry - 1) * 100 >= 2.0:
                trail = peak * (1 - 0.015)
                if b["l"] <= trail: return (trail / entry - 1) * 100, j
            if lo <= -3: return -3.0, j
        elif mode == "Xa TP3/SL3":
            if lo <= -3: return -3.0, j
            if hi >= 3: return 3.0, j
        if b["m"] >= "1330":
            return (b["c"] / entry - 1) * 100, j
    return (bars[-1]["c"] / entry - 1) * 100, len(bars) - 1


def simulate_portfolio(day_signals, slots):
    """슬롯 재활용 포트폴리오. day_signals=[(entry_idx, ret%, exit_idx)] 시각순.
    반환: 일수익률%(= (1/slots)*Σ 실행거래수익, 자본 1/slots씩 배분)."""
    sig = sorted(day_signals, key=lambda s: s[0])
    busy = []  # 각 슬롯이 비는 exit_idx
    total = 0.0; taken = 0
    for ei, ret, xi in sig:
        busy = [b for b in busy if b > ei]      # ei 시점에 빈 슬롯 회수
        if len(busy) < slots:
            busy.append(xi); total += ret; taken += 1
    return total / slots, taken


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-25")
    ap.add_argument("--end", default="2026-12-31")
    args = ap.parse_args()
    conn = _conn()
    reg = regimes(conn, args.start, args.end)
    dates = [r["trade_date"] for r in conn.execute(
        "SELECT DISTINCT trade_date FROM intraday_bars WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
        (args.start, args.end))]

    entries = _entry_rules()
    exits = ["Xa TP3/SL3", "Xb TP2/SL2", "Xc 트레일(발동+2·폭1.5)", "Xe TP5/SL3",
             "Xf 트레일(발동+3·폭2)", "Xg 추세라이딩(발동+1.5·폭2.5·무캡)", "Xd 종가보유[대조]"]
    # results[(entry,exit,regime)] = list of returns(net)
    res = defaultdict(list)
    perday_res = defaultdict(list)  # [(entry,exit,date)] = returns
    port_sig = defaultdict(list)    # [(exit_variant,date)] = [(entry_idx, net_ret, exit_idx)]
    E6 = "E6 강세근접VWAP(cfo>0·VWAP0~1%위)"
    day_syms = 0
    for date in dates:
        rgm = reg.get(date, ("?", 0))[0]
        syms = [r["symbol"] for r in conn.execute(
            "SELECT DISTINCT symbol FROM intraday_bars WHERE trade_date=?", (date,))]
        for sym in syms:
            bars = load_minute_bars(conn, date, sym)
            if not covered(bars):
                continue
            day_syms += 1
            bars = with_features(bars)
            for ename, (win_end, trig) in entries.items():
                ei = _find_entry(bars, win_end, trig)
                if ei is None or ei >= len(bars) - 1:
                    continue
                for xmode in exits:
                    ret = _exit(bars, ei, xmode) - ROUND_TRIP_COST
                    res[(ename, xmode, rgm)].append(ret)
                    perday_res[(ename, xmode, date)].append(ret)
                if ename == E6:   # 포트폴리오 재활용 시뮬용 신호 수집(진입/청산 시각 포함)
                    for xm in ["Xc 트레일(발동+2·폭1.5)", "Xa TP3/SL3"]:
                        r, xi = _exit_with_time(bars, ei, xm)
                        port_sig[(xm, date)].append((ei, r - ROUND_TRIP_COST, xi))
                    rp, xip = _exit_partial(bars, ei)
                    port_sig[("Xh 분할60%@+2·러너40%", date)].append((ei, rp - ROUND_TRIP_COST, xip))

    def stat(xs):
        if not xs:
            return (0, 0.0, 0.0)
        wins = sum(1 for x in xs if x > 0)
        return (len(xs), 100 * wins / len(xs), sum(xs) / len(xs))

    print(f"\n{'='*90}\n상승장 필승패턴 탐색 — {args.start}~{args.end} · 종일커버 종목-일 {day_syms}건 · 왕복비용 {ROUND_TRIP_COST}%")
    reg_days = defaultdict(list)
    for d, (g, cr) in sorted(reg.items()):
        if d in dates:
            reg_days[g].append(d)
    print("레짐 일수: " + " · ".join(f"{g} {len(v)}일" for g, v in reg_days.items()))
    print('='*90)

    for rgm in ["상승", "보합", "하락"]:
        print(f"\n■ {rgm}장 — 진입규칙 × 청산규칙 (n=표본 / 승률% / 평균손익% ← 기대값)")
        print(f"{'진입규칙':<30}" + "".join(f"{x.split()[0]:>18}" for x in exits))
        for ename in entries:
            cells = []
            for xmode in exits:
                n, wr, ev = stat(res[(ename, xmode, rgm)])
                cells.append(f"{n:>3}/{wr:>3.0f}%/{ev:>+5.2f}")
            print(f"{ename:<30}" + "".join(f"{c:>18}" for c in cells))

    # ── 로버스트니스: 챔피언 조합의 상승장 일자별 성적 (특정일 몰림 여부)
    champs = [("E6 강세근접VWAP(cfo>0·VWAP0~1%위)", "Xa TP3/SL3"),
              ("E6 강세근접VWAP(cfo>0·VWAP0~1%위)", "Xc 트레일(발동+2·폭1.5)")]
    print(f"\n{'='*90}\n[로버스트니스] 챔피언 조합 — 상승장 일자별 (특정일 몰림 아닌지)\n{'='*90}")
    up_days = sorted([d for d in dates if reg.get(d, ('?', 0))[0] == "상승"])
    for ename, xmode in champs:
        print(f"\n▸ {ename.split('(')[0]} + {xmode}")
        print(f"  {'날짜':<11}{'KOSPI':>8}{'n':>4}{'승률':>6}{'EV%':>7}   개별손익%")
        for d in up_days:
            bydaysym = perday_res.get((ename, xmode, d), [])
            if not bydaysym:
                print(f"  {d:<11}{reg[d][1]:>+7.2f}%{0:>4}     -      -")
                continue
            n = len(bydaysym); wr = 100*sum(1 for x in bydaysym if x > 0)/n; ev = sum(bydaysym)/n
            detail = " ".join(f"{x:+.1f}" for x in sorted(bydaysym, reverse=True))
            print(f"  {d:<11}{reg[d][1]:>+7.2f}%{n:>4}{wr:>5.0f}%{ev:>+7.2f}   {detail}")

    # ── 코스피 상승분 대비 예상 수익률(포착률) — 일 포트폴리오 = E6 신호 균등배분 1회전
    print(f"\n{'='*90}\n[포착률] 코스피 상승분 대비 예상 시스템 수익률 — 상승장 일별\n"
          f"  가정: 그날 E6 신호에 자본 균등배분(1회전, 재활용 미반영=보수적). 일수익률=거래평균.\n{'='*90}")
    cap_exits = ["Xc 트레일(발동+2·폭1.5)", "Xa TP3/SL3", "Xg 추세라이딩(발동+1.5·폭2.5·무캡)"]
    ename = "E6 강세근접VWAP(cfo>0·VWAP0~1%위)"
    print(f"\n  진입=E6 · 청산별 일수익률 / 포착률(=시스템÷코스피)")
    print(f"  {'날짜':<11}{'KOSPI':>8}" + "".join(f"{x.split()[0]:>10}{'포착':>7}" for x in cap_exits))
    sums = {x: [] for x in cap_exits}; caps = {x: [] for x in cap_exits}
    for d in up_days:
        kchg = reg[d][1]
        row = f"  {d:<11}{kchg:>+7.2f}%"
        for x in cap_exits:
            rr = perday_res.get((ename, x, d), [])
            if rr and kchg > 0:
                dayret = sum(rr) / len(rr)
                cap = dayret / kchg * 100
                sums[x].append(dayret); caps[x].append(cap)
                row += f"{dayret:>+9.2f}%{cap:>6.0f}%"
            else:
                row += f"{'-':>10}{'-':>7}"
        print(row)
    print(f"  {'─'*80}")
    avgrow = f"  {'평균':<11}{sum(reg[d][1] for d in up_days)/len(up_days):>+7.2f}%"
    for x in cap_exits:
        da = sum(sums[x])/len(sums[x]) if sums[x] else 0
        ca = sum(caps[x])/len(caps[x]) if caps[x] else 0
        avgrow += f"{da:>+9.2f}%{ca:>6.0f}%"
    print(avgrow)

    # ── 포착률 끌어올리기: 재활용(슬롯 회전) + 분할익절+러너 (상승장 한정)
    print(f"\n{'='*90}\n[포착률 향상] E6 · 슬롯 재활용 + 분할익절+러너 — 레짐별 (하락장 방어 확인)\n"
          f"  일수익률 = (1/슬롯)×Σ실행거래. 슬롯<신호면 재활용 발생. Xh=60%@+2확정·40%러너.\n{'='*90}")
    variants = ["Xc 트레일(발동+2·폭1.5)", "Xa TP3/SL3", "Xh 분할60%@+2·러너40%"]
    for slots in (6, 8, 10):
        print(f"\n  ▸ 슬롯 {slots}개 (자본 1/{slots}씩)")
        print(f"  {'레짐':<6}" + "".join(f"{v.split()[0]:>14}{'포착':>7}" for v in variants))
        for rgm in ["상승", "보합", "하락"]:
            rdays = [d for d in dates if reg.get(d, ('?', 0))[0] == rgm]
            row = f"  {rgm:<6}"
            for v in variants:
                drets, dcaps = [], []
                for d in rdays:
                    sigs = port_sig.get((v, d), [])
                    if not sigs:
                        continue
                    dr, _tk = simulate_portfolio(sigs, slots)
                    drets.append(dr)
                    if reg[d][1] > 0:
                        dcaps.append(dr / reg[d][1] * 100)
                da = sum(drets)/len(drets) if drets else 0
                ca = sum(dcaps)/len(dcaps) if dcaps else None
                row += f"{da:>+13.2f}%" + (f"{ca:>6.0f}%" if ca is not None else f"{'-':>7}")
            print(row)
    print("\n  ※ 하락장 행은 'E6를 하락장에도 켰다면'의 가정치 — 실제 배포는 risk_on 한정이라 하락장 방어는 현행 눌림 유지(불변).")
    print()


if __name__ == "__main__":
    main()

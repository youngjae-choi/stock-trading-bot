"""전략 사양서(STRATEGY_SPEC.md) 단일 진실원천 — 의도 vs 실측 대조 로직.

이 모듈이 **전략 의도(INTENT)의 단일 소스**다. CLI(`scripts/strategy_spec_sync.py`)와
서버 워치독(ops_watchdog)이 이 모듈을 import해 같은 기준으로 드리프트를 판단한다.

- `check_drift()`  : 라이브 DB 실측 ≠ 의도 불일치 목록(문장) 반환. 파일 미수정. 워치독용.
- `sync_strategy_spec(write=True)` : STRATEGY_SPEC.md의 B(실측)·C(드리프트) 블록 재작성.
  멱등 — 타임스탬프 외 변화가 없으면 파일 미수정(git 노이즈 방지). CLI/EOD용.

읽기 전용(라이브 DB mode=ro) + STRATEGY_SPEC.md 파일 쓰기만. KIS 호출 없음.

★ 전략을 바꾸면: STRATEGY_SPEC.md의 A절(의도) + 아래 INTENT 딕셔너리를 함께 고친다.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data" / "stock_trading_bot.sqlite3"
SPEC = ROOT / "STRATEGY_SPEC.md"

# ─────────────────────────────────────────────────────────────────────────
# 의도(INTENT) — 이 시스템이 이렇게 동작해야 한다. 드리프트 대조의 기준값.
# 전략을 바꾸면 여기와 STRATEGY_SPEC.md A절을 함께 수정한다.
# ─────────────────────────────────────────────────────────────────────────
INTENT_SETTINGS: dict[str, object] = {
    "engine.entry_vwap_pullback_mode": "enforce",   # 눌림목 게이트 활성(고점추격 차단)
    "engine.max_price_change_pct": 4.0,             # 고점추격 상한(시가대비 +4% 초과 매수 차단)
    "engine.min_price_change_pct": 1.5,             # 진입 최소 등락률
    "engine.entry_execute_start_time": "09:30",     # 실매매 시작(이전은 shadow)
    "risk.flash_crash_threshold_pct": -2.0,         # 폭락 방어모드 발동선
    "engine.s10_llm_review_enabled": False,         # LLM 복기 제거(수동통제)
    "engine.loss_autotune_apply_enabled": False,    # 손실 auto-tuner 관찰전용
}
# 레짐 SET별 매도 파라미터 의도 (regime SET applied_settings 와 대조)
INTENT_REGIME_SETS: dict[str, dict[str, float]] = {
    "risk_on":  {"max_positions": 12, "stop_loss_rate": -0.035, "take_profit_rate": 0.08,
                 "trailing_activate_profit": 0.04, "trailing_stop_rate": 0.02},
    "neutral":  {"max_positions": 7,  "stop_loss_rate": -0.02,  "take_profit_rate": 0.045,
                 "trailing_activate_profit": 0.025, "trailing_stop_rate": 0.012},
    "risk_off": {"max_positions": 4,  "stop_loss_rate": -0.012, "take_profit_rate": 0.025,
                 "trailing_activate_profit": 0.015, "trailing_stop_rate": 0.008},
}
_FLOAT_TOL = 1e-9


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def read_live_settings(conn) -> dict[str, object]:
    """system_settings에서 의도 대상 키의 실측값(파싱)을 읽는다. 없으면 미포함."""
    out: dict[str, object] = {}
    rows = conn.execute(
        "SELECT key, value_json FROM system_settings WHERE key IN (%s)"
        % ",".join("?" * len(INTENT_SETTINGS)),
        tuple(INTENT_SETTINGS),
    ).fetchall()
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value_json"])
        except (json.JSONDecodeError, TypeError):
            out[r["key"]] = r["value_json"]
    return out


def read_live_regime_sets(conn) -> dict[str, dict]:
    """레짐 라벨별 최신 적용 SET의 applied_settings를 읽는다."""
    rows = conn.execute(
        "SELECT regime_label, applied_settings, applied_at FROM regime_set_applications "
        "WHERE regime_label IS NOT NULL ORDER BY applied_at"
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:  # 나중 것이 덮어씀 = 최신 유지
        try:
            out[r["regime_label"]] = json.loads(r["applied_settings"])
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def read_current_regime(conn) -> dict:
    """현재 활성(current_flag=1) 레짐 1건."""
    r = conn.execute(
        "SELECT trade_date, applied_at, regime_label, trigger, kospi_change_pct "
        "FROM regime_set_applications WHERE current_flag=1 ORDER BY applied_at DESC LIMIT 1"
    ).fetchone()
    return dict(r) if r else {}


def _num_eq(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) <= _FLOAT_TOL
    except (TypeError, ValueError):
        return a == b


def compute_drift(intent_settings, live_settings, intent_sets, live_sets) -> list[str]:
    """의도 ≠ 실측 불일치 목록(사람이 읽는 문장). 대조 로직의 단일 소스."""
    drift: list[str] = []
    for key, want in intent_settings.items():
        if key not in live_settings:
            drift.append(f"⚠ `{key}` 미설정 — 의도 `{want}` (코드기본 의존, DB 명시 권장)")
            continue
        got = live_settings[key]
        same = _num_eq(got, want) if isinstance(want, (int, float)) and not isinstance(want, bool) else got == want
        if not same:
            drift.append(f"🔴 `{key}` 불일치 — 의도 `{want}` vs 실측 `{got}`")
    for label, want in intent_sets.items():
        got = live_sets.get(label)
        if got is None:
            drift.append(f"⚠ 레짐 SET `{label}` 실측 없음 — 의도 존재")
            continue
        for field, wv in want.items():
            gv = got.get(field)
            if gv is None or not _num_eq(gv, wv):
                drift.append(f"🔴 SET `{label}.{field}` 불일치 — 의도 `{wv}` vs 실측 `{gv}`")
    return drift


def check_drift() -> list[str]:
    """라이브 실측을 의도와 대조한 드리프트 목록. 파일 미수정 — 워치독/CI용."""
    with _conn() as conn:
        live_settings = read_live_settings(conn)
        live_sets = read_live_regime_sets(conn)
    return compute_drift(INTENT_SETTINGS, live_settings, INTENT_REGIME_SETS, live_sets)


def _fmt_live_block(live_settings, live_sets, current, drift_count) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    L = [f"_자동 생성: {ts} · `scripts/strategy_spec_sync.py` · 손대지 마라._", ""]
    cur = current.get("regime_label", "?")
    at = str(current.get("applied_at", ""))[:19]
    trg = current.get("trigger", "")
    L += [f"**현재 활성 레짐:** `{cur}` (trigger={trg}, at={at})", "",
          "**전략 게이트/설정 (system_settings 실측):**", "",
          "| 설정 | 실측값 |", "|---|---|"]
    for key in INTENT_SETTINGS:
        v = live_settings.get(key, "_(미설정·코드기본)_")
        L.append(f"| `{key}` | `{v}` |")
    L += ["", "**레짐 SET별 매도 파라미터 (실측):**", "",
          "| 레짐 | max종목 | 손절 | 익절 | 트레일발동 | 트레일폭 |", "|---|---|---|---|---|---|"]
    for label in ("risk_on", "neutral", "risk_off", "volatile"):
        s = live_sets.get(label)
        if not s:
            continue
        L.append("| {} | {} | {} | {} | {} | {} |".format(
            label, s.get("max_positions", "-"), s.get("stop_loss_rate", "-"),
            s.get("take_profit_rate", "-"), s.get("trailing_activate_profit", "-"),
            s.get("trailing_stop_rate", "-")))
    L += ["", f"_드리프트 {drift_count}건 (아래 C절 참조)_"]
    return "\n".join(L)


def _fmt_drift_block(drift) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not drift:
        return (f"_자동 생성: {ts}_\n\n✅ **드리프트 없음** — 실측이 의도와 일치한다. "
                "시스템이 사양대로 동작 중.")
    body = "\n".join(f"- {d}" for d in drift)
    return (f"_자동 생성: {ts}_\n\n🔴 **드리프트 {len(drift)}건** — 실측이 의도를 벗어났다. "
            "각 항목을 의도대로 되돌리거나, 의도가 바뀐 것이면 A절+INTENT를 갱신하라.\n\n" + body)


def _replace_block(text: str, tag: str, new_body: str) -> str:
    pat = re.compile(rf"(<!-- AUTO:{tag} START -->)(.*?)(<!-- AUTO:{tag} END -->)", re.DOTALL)
    if not pat.search(text):
        raise ValueError(f"STRATEGY_SPEC.md에 AUTO:{tag} 마커가 없다.")
    return pat.sub(lambda m: f"{m.group(1)}\n{new_body}\n{m.group(3)}", text)


def _strip_timestamps(text: str) -> str:
    """멱등 비교용 — 타임스탬프 줄만 제거(실질 내용 변화만 감지)."""
    return re.sub(r"_자동 생성:[^\n]*", "", text)


def sync_strategy_spec(write: bool = True) -> dict:
    """실측·드리프트를 계산하고, 실질 변화가 있을 때만 STRATEGY_SPEC.md를 재작성한다.
    멱등 — 타임스탬프 외 변화가 없으면 파일을 건드리지 않는다(git 노이즈 방지).
    반환: {drift, changed, drift_items}.
    """
    with _conn() as conn:
        live_settings = read_live_settings(conn)
        live_sets = read_live_regime_sets(conn)
        current = read_current_regime(conn)
    drift = compute_drift(INTENT_SETTINGS, live_settings, INTENT_REGIME_SETS, live_sets)
    old = SPEC.read_text(encoding="utf-8")
    new = _replace_block(old, "LIVE", _fmt_live_block(live_settings, live_sets, current, len(drift)))
    new = _replace_block(new, "DRIFT", _fmt_drift_block(drift))
    changed = _strip_timestamps(old) != _strip_timestamps(new)
    if write and changed:
        SPEC.write_text(new, encoding="utf-8")
    return {"drift": len(drift), "changed": changed, "drift_items": drift}

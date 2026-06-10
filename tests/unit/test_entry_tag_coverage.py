"""진입 태깅 커버리지 — 모든 매수 경로에서 trade_entry_tags 기록 (2026-06-10 갭 수정).

배경: 태깅이 탐색 OR 경로(_maybe_exploration_buy)에만 있어 베이스라인 게이트·교체매매
경로의 매수는 태그가 안 찍혔다(6/10 매매 5종목 중 4종목 무태그 → 학습 표본 누락).
수정: 태깅을 단일 길목인 _emit_signal로 이동, matched dict에서 발화그룹을 유도한다.
"""

from backend.services.engine.decision_engine import _derive_tag_decision


def test_baseline_gate_path_tags_with_baseline_group():
    matched = {
        "pass": True,
        "matched": {"volume_ratio": True, "price_change": True, "time_window": True},
        "observed_values": {"change_rate": 3.2, "volume_ratio": 2.7},
    }
    d = _derive_tag_decision(matched)
    assert d["fired"] == ["베이스라인(기존게이트)"]
    # 관측값과 조건 통과 여부가 condition_states로 보존
    assert d["condition_states"]["change_rate"] == 3.2
    assert d["condition_states"]["volume_ratio"] == 2.7


def test_exploration_path_keeps_fired_groups_and_states():
    matched = {
        "exploration": True,
        "fired_groups": ["급등+체결강도"],
        "condition_states": {"체결강도": 1.2},
    }
    d = _derive_tag_decision(matched)
    assert d["fired"] == ["급등+체결강도"]
    assert d["condition_states"] == {"체결강도": 1.2}


def test_replacement_path_tags_with_replacement_group():
    d = _derive_tag_decision({"replacement": True})
    assert d["fired"] == ["교체매매"]

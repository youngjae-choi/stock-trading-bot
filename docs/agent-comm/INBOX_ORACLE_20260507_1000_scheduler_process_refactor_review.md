# INBOX_ORACLE - 2026-05-07 10:00 KST - 스케줄 프로세스 구조 변경 리뷰

## 요청자

Sisyphus

## 담당 페르소나

Oracle

## 배경

Executor가 다음 지시서에 따라 스케줄러 구조를 변경했다.

- 지시: `docs/agent-comm/INBOX_EXECUTOR_20260507_0945_scheduler_process_refactor.md`
- 결과: `docs/agent-comm/OUTBOX_EXECUTOR_20260507_0945_scheduler_process_refactor.md`

목표:

- 개별 S1~S5-A 시간 설정 대신 `schedule_trade_prep_time` 하나로 S1→S5-A 순차 실행
- S6/S7/S8/S11 현행 유지
- `schedule_postprocess_time` 하나로 S9→S10 순차 실행
- KIS 휴장일 조회 실패/모의투자 미지원/unknown을 비거래일로 오판하지 않게 3상태화

## 리뷰 목표

1. Scheduler job 등록이 의도대로 바뀌었는지 확인.
   - trade prep pipeline job 1개
   - S6 유지
   - S7/S8 실시간 구조 유지
   - postprocess pipeline job 1개
   - S11 유지
   - S1~S5 개별 cron 제거/legacy화
2. trade prep pipeline이 S1→S2→S3→S4→S5→S5-V→S5-A 순서로 실행되도록 구현됐는지 확인.
3. postprocess pipeline이 S9→S10 순서로 실행되도록 구현됐는지 확인.
4. trading day 3상태가 안전한지 확인.
   - 명확한 closed만 skip true
   - unknown/failure는 skip false + WARN
   - KIS 모의투자 미지원/빈 응답을 closed로 오판하지 않음
5. Settings/UI에서 운영자가 개별 S1~S5 시간을 설정해야 하는 혼선이 줄었는지 확인.
6. 기존 API/Diagnostics/Today 표시와 충돌하지 않는지 확인.
7. S1 토큰 갱신 실패 시 후속 단계 진행 정책이 적절한지, 위험하면 finding으로 남겨라.
8. S9 내부 실패와 S10 진행 정책이 적절한지, 위험하면 finding으로 남겨라.

## 금지 사항

- 파일 수정 금지.
- git commit 금지.
- 실제 S1~S11 단계 실행 금지.
- `/api/v1/decision/activate` 호출 금지.
- 주문/매수/매도/청산 API 호출 금지.
- 실계좌/KIS 주문성 API 호출 금지.
- 외부 LLM/KIS 호출 금지.

## 필수 검증

- `.venv/bin/python -m compileall -q backend`
- `git diff --check`
- 외부 호출 없는 scheduler/settings/trading-day smoke 재확인
- 가능하면 scheduler job IDs를 build만 해서 확인하되, scheduler start/job 실행은 하지 말 것

## 결과 보고 파일

검토 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_ORACLE_20260507_1000_scheduler_process_refactor_review.md`

포함 항목:

- Findings 우선: P1/P2/P3, 파일/라인, 영향, 수정 제안
- 테스트 결과
- 최종 판단: 배포 가능 / 조건부 가능 / 불가
- 남은 위험

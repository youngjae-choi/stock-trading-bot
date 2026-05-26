# EOD 자동 검증 리포트

> 2026-05-27 ~ 2026-05-31 (5일) 자율 운영 기간 동안 매일 18:30 KST에 cron이 자동 생성한 리포트가 누적됩니다.

## 운영 구성

- **스크립트**: `scripts/eod_verify.py`
- **실행 시각**: 매일 18:30 KST (09:30 UTC)
- **종료 조건**: `AUTO_RUN_DEADLINE = 2026-05-31` 이후 자동 종료
- **cron**: `30 9 * * * .../.venv/bin/python .../scripts/eod_verify.py --auto`
- **cron 로그**: `logs/eod_verify_cron.log`

## 결과 파일 구조

```
docs/eod-reports/
  ├── 2026-05-26_eod_report.md   (사전 테스트 — 어제 데이터)
  ├── 2026-05-27_eod_report.md   (1일차)
  ├── 2026-05-28_eod_report.md   (2일차)
  ├── 2026-05-29_eod_report.md   (3일차)
  ├── 2026-05-30_eod_report.md   (4일차, 토)
  ├── 2026-05-31_eod_report.md   (5일차, 일)
  └── README.md                   (본 파일)
```

각 리포트 상단 5줄 요약:
- 거래일 여부
- PASS / WARN / FAIL / SKIP / INFO 카운트
- Critical FAIL 건수 + 즉시 조치 필요 표기
- Critical FAIL 항목 요약 (있으면)

## PM이 돌아온 후

1. `docs/eod-reports/2026-05-2*_eod_report.md` 5개 파일을 시간순으로 확인
2. 각 리포트의 "Critical FAIL 요약" 섹션 우선 확인
3. WARN/INFO는 데이터 트렌드 분석용 (5일간 누적 패턴 보기)
4. 비교 분석은 별도로 진행 (스크립트 종료 후 PM이 직접)

## cron 제거 (자율 운영 종료 후)

```bash
# 현재 등록된 cron 확인
crontab -l

# 모두 제거
crontab -r

# 또는 특정 줄만 제거 (수동 편집)
crontab -e
```

스크립트 자체는 `AUTO_RUN_DEADLINE` 이후 자동으로 exit 2로 종료되므로 6일째부터는 새 리포트가 생성되지 않습니다. cron 자체는 계속 등록돼 있으니 깨끗하게 정리하려면 위 명령 사용.

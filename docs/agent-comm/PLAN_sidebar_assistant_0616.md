# 사이드바 화면-인지 어시스턴트 — 개발계획서 v0.2 (MD파일/구독 방식)

> v0.1(Anthropic API key·스트리밍·tool_use 직접구현)은 **폐기**. PM 결정(2026-06-16):
> API 토큰 과금 회피 → **공유 MD 파일을 매개로, 기존 구독(CLI Claude)과 턴제 대화**. 실시간 불필요.

## 원본 요구사항 (PM 발화 요지)
> 사이드바 챗봇. 현재 화면 컨텍스트(JSON)를 주입해 "내가 보는 화면을 LLM이 같이 보는" 효과.
> 복붙 귀찮으니 자동 주입. 마이크 입력. **API key 아닌 구독으로. 실시간 아니어도 됨 — MD 파일에 서로 써가며 대화.**

## 핵심 구조 (API 미사용 = 한계비용 0)
1. 웹 콘솔이 **현재 화면 컨텍스트(JSON)** + PM 입력을 **날짜별 공유 MD에 append**.
2. PM이 CLI에서 Claude(나)에게 알림 → 나는 그 MD를 읽어 "같은 화면을 보고" 분석·답변을 **같은 MD에 append**.
3. 콘솔 패널은 그 MD를 폴링 표시 → PM이 웹에서도 답변 확인.
- 웹서치·내부조회 tool은 **불필요**(내가 CLI에서 이미 사용). 스트리밍/SSE/tool_use 루프 전부 제거.

## 파일 모델: 날짜별
- `docs/agent-comm/console_chat/console_chat_YYYYMMDD.md` (KST 기준일).
- append 포맷: `\n## [HH:MM] 🧑 PM @<screen_id>\n<note>\n\n\`\`\`json\n<screen_context>\n\`\`\`\n` / 내 답변은 `## [HH:MM] 🤖 Claude\n...`.

## 변경/신규 파일
| 파일 | 유형 | 내용 |
|------|------|------|
| `backend/api/routes/assistant.py` | 신규 | `POST /api/v1/assistant/note`(append, 콘솔 auth), `GET /api/v1/assistant/note?date=`(조회) |
| `backend/services/console_chat_store.py` | 신규(소) | 날짜별 MD 경로·append·read 헬퍼 |
| `backend/static/js/screens/console-assistant.js` | 신규 | 사이드바 패널: 화면 컨텍스트 수집·🎤STT 입력·전송·MD 폴링 표시 |
| `backend/static/console.html` / `console.css` | 수정 | 패널 마크업·스타일·토글 |
| `backend/main.py` | 수정 | 라우터 등록 |

## 화면 컨텍스트 수집(v1)
- 활성 `.screen`의 screen_id + 렌더된 핵심 지표/카드 텍스트를 compact JSON으로 직렬화(범용 추출기). 화면별 정밀 추출기는 후속.

## 요구사항 대조표
| 요구사항 | 반영 | 비고 |
|----------|------|------|
| 화면 컨텍스트 자동 주입(복붙 제거) | ✓ | 버튼→MD append |
| "같은 화면 보는" 효과 | ✓ | JSON 컨텍스트로 내가 화면 인지 (스크린샷은 후속 옵션) |
| API 아닌 구독 | ✓ | Anthropic API 미호출 = 과금 0 |
| 실시간 아니어도 됨 | ✓ | 턴제(MD 매개) |
| 마이크 입력 | ✓ | Web Speech API(STT) |
| function_call/웹서칭 | ✓(간접) | 내가 CLI tool로 수행 |

## 리스크
- 데이터: MD에 계좌·매매 데이터 평문 기록 → repo 내 `docs/agent-comm/`(로컬). 외부 전송 없음(API 미사용). git 커밋 대상 제외 권장(.gitignore).
- 동시쓰기: append-only + 짧은 락/원자적 쓰기로 충돌 회피.
- 인증: append 엔드포인트 콘솔 auth 필수.

## 완료 기준
- [ ] 패널에서 화면 컨텍스트+노트 전송 → 날짜별 MD에 정상 append
- [ ] 🎤 STT 입력 동작
- [ ] 패널이 MD 대화 폴링 표시(내 답변 포함)
- [ ] auth 없이는 차단, .gitignore 반영
- [ ] Playwright E2E

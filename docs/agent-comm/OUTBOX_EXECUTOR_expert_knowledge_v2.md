# OUTBOX_EXECUTOR_expert_knowledge_v2

## 작업 요약

Expert Knowledge 화면을 PDF 업로드 → 텍스트 추출 → LLM 전략 분석 → 운영자 승인 → Settings 반영 흐름으로 확장했다.
기존 `strategy_knowledge_items` 테이블과 기존 수동 CRUD API는 삭제하지 않고 유지했다.

## 변경 파일

- `requirements.txt`
  - `pypdf>=4.0.0` 추가
- `backend/services/engine/expert_knowledge.py`
  - `MAPPABLE_SETTINGS` 추가
  - `extract_pdf_text(file_bytes)` 추가
  - `analyze_strategy_with_llm(text)` 추가
  - LLM JSON 파싱/정규화 및 Settings 키 allowlist 검증 추가
- `backend/api/routes/expert_knowledge.py`
  - `require_console_user` router dependency 추가
  - `POST /api/v1/expert-knowledge/upload-pdf` 추가
  - `POST /api/v1/expert-knowledge/apply-strategy/{analysis_id}` 추가
  - `GET /api/v1/expert-knowledge/analyses` 추가
  - 현재 환경에서 `python-multipart` 미설치 시 앱 기동이 깨지지 않도록 표준 라이브러리 기반 multipart 파싱 적용
- `backend/services/db.py`
  - `pdf_analyses` 테이블 및 `idx_pdf_analyses_created` 인덱스 추가
- `backend/static/console.html`
  - Expert Knowledge 섹션을 PDF 업로드/분석 결과/분석 이력 UI로 교체
  - `ekUploadPdf`, `ekRenderResult`, `ekApplyStrategy`, `ekReset`, `ekLoadHistory` 추가
  - `showScreen("expert-knowledge")` 진입 시 `ekLoadHistory()` 호출로 변경

## 검증 결과

- `python3 -m py_compile backend/api/routes/expert_knowledge.py backend/services/engine/expert_knowledge.py backend/services/db.py` : OK
- `HTMLParser().feed(open("backend/static/console.html").read())` : OK
- `import backend.api.routes.expert_knowledge` : OK
- `initialize_database()` 후 `pdf_analyses` 테이블 조회 : OK
- `python3 -c "from pypdf import PdfReader"` : FAIL
  - 원인: 현재 실행 환경에 `pypdf`가 설치되어 있지 않음
  - `python3 -m pip install 'pypdf>=4.0.0'` 실행 시 네트워크 제한으로 PyPI 접근 실패

## 완료 체크리스트

- [x] `requirements.txt`에 `pypdf>=4.0.0` 추가
- [x] `extract_pdf_text()` 함수 추가
- [x] `analyze_strategy_with_llm()` 함수 추가
- [x] `pdf_analyses` DB 테이블 추가
- [x] `POST /api/v1/expert-knowledge/upload-pdf` 엔드포인트 추가
- [x] `POST /api/v1/expert-knowledge/apply-strategy/{analysis_id}` 엔드포인트 추가
- [x] `GET /api/v1/expert-knowledge/analyses` 엔드포인트 추가
- [x] Expert Knowledge 화면 HTML 재설계
- [x] JS 함수 추가
- [x] showScreen에서 `ekLoadHistory()` 호출로 교체
- [x] `require_console_user` 추가
- [x] py_compile OK
- [x] HTML parse OK
- [ ] pypdf import OK
- [x] pdf_analyses 테이블 생성 확인

## 잔여 리스크 / 확인 필요

- 현재 샌드박스 네트워크 제한 때문에 `pypdf` 설치 검증과 실제 PDF 텍스트 추출 런타임 검증은 완료하지 못했다.
- LLM 실제 호출은 외부 API 키와 네트워크가 필요하므로 현재 환경에서는 최종 응답 품질 검증이 제한된다.
- `backend/static/console.html`에는 이번 작업 전부터 다른 화면 관련 미커밋 변경이 섞여 있었다. 본 작업은 Expert Knowledge 섹션 및 관련 JS 진입점만 대상으로 했다.

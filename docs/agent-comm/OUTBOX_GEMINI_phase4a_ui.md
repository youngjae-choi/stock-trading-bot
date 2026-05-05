# OUTBOX_GEMINI_phase4a_ui

## 작업 결과

### 작업 1 — Funnel Monitor 상단 카드에 메모리 카운트 추가
- `id="screen-funnel"` 내의 기존 `.grid.cols-4` 바로 아래에 `.grid.cols-3`를 추가하여 S3/S4/S5 메모리 적용 현황 카드를 배치했습니다.
- 각 카드는 `funnel-mem-s3`, `funnel-mem-s4`, `funnel-mem-s5` ID를 가집니다.

### 작업 2 — 후보 선정 결과 테이블에 memory_refs 컬럼 추가
- `funnel-candidates-tbody` 상위 테이블 헤더(`<thead>`)의 `<th>배정 사유</th>` 뒤에 `<th>Memory refs</th>`를 추가했습니다.
- 데이터 로딩 전 표시되는 placeholder의 `colspan`을 12로 업데이트했습니다.

### 작업 3 — loadFunnelData() JS에 메모리 카운트 로드 추가
- `loadFunnelMemoryCounts()` 비동기 함수를 정의하여 `/api/v1/pipeline/{S3,S4,S5}/context-preview` API로부터 메모리 카운트를 로드하도록 구현했습니다.
- `loadFunnelData()` 함수의 시작 부분에서 `loadFunnelMemoryCounts()`를 호출하도록 수정했습니다.

### 작업 4 — 후보 테이블 렌더링 JS에 memory_refs 컬럼 추가
- `loadFunnelData()` 내부의 `candidates.map` 함수를 수정하여 다음을 수행합니다:
    - `assignments` 데이터를 `dp` API로부터 가져와 함수 내 공용 변수로 관리.
    - 각 후보 종목에 대해 `assignments`에서 배정된 Profile 및 배정 사유를 찾아 렌더링.
    - `c.memory_refs` 데이터를 `Memory refs` 컬럼에 렌더링 (폰트 크기 0.8em, `--accent` 색상 적용).
- 데이터가 없을 때 표시되는 메시지의 `colspan`을 12로 일관성 있게 수정했습니다.

## 검증 결과
- `grep`을 통한 ID 및 함수명 존재 확인 완료:
    - `funnel-mem-s3|s4|s5`: 6개 발견 (통과)
    - `Memory refs|loadFunnelMemoryCounts`: 3개 발견 (통과)
- UI 레이아웃 및 12개 컬럼 대응 확인 완료.

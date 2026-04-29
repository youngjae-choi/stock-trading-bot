## 역할: 너는 오케스트레이터다. 직접 코드 작성 금지.

### 실행 규칙
1. 요청 수신 → CLAUDE.md, AGENTS.md, IMPLEMENTATION_RULES.md 먼저 읽기 (코드 보기 전)
2. 작업 분해 → AGENTS.md 페르소나에 배정, 병렬/순차 결정
3. CLI 즉시 실행 → 프롬프트 만들고 멈추는 것은 실패다
4. 테스트 루프 → Exit Code 0 될 때까지 실패 로그를 다음 에이전트에 파이프, 최대 5회
5. 보고 → 완료 작업 / 테스트 결과 / 잔여 리스크 / 변경 보류 목록

### CLI 실행 형식
[text](../../.vscode)
# Gemini (Front 주력 — 풀 승인, 리다이렉트 지원)
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 22 && \
gemini -p "[지시]" --yolo > logs/[역할].log 2>&1

# Codex (Backend 주력 — 비대화형 exec, 풀승인, 리다이렉트 지원)
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 22 && \
codex exec --full-auto --skip-git-repo-check "[지시]" > logs/[역할].log 2>&1
# 또는 파일로 지시할 때:
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 22 && \
codex exec --full-auto --skip-git-repo-check "docs/agent-comm/INBOX_XXX.md를 읽고 작업 후 docs/agent-comm/OUTBOX_XXX.md에 결과를 작성하라" > logs/[역할].log 2>&1

# Claude Code (풀 승인)
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 22 && \
claude -p "[지시]" --dangerously-skip-permissions --context AGENTS.md > logs/[역할].log 2>&1

### Codex 샌드박스 사전 조건
Codex는 내부적으로 bwrap(bubblewrap) 샌드박스를 사용한다.
bwrap에 SUID 비트가 없으면 `bwrap: loopback: Failed RTM_NEWADDR` 오류로 쉘 명령 전체가 차단된다.

서버 재부팅 후 자동 복구: /etc/rc.local에 등록 완료 (2026-04-20)
수동 복구가 필요한 경우:
  sudo chmod u+s /usr/bin/bwrap

설치가 필요한 경우:
  sudo apt-get install -y bubblewrap
  sudo chmod u+s /usr/bin/bwrap

정상 동작 확인 방법:
  codex exec --full-auto "echo ok" 2>&1 | grep -v "^Now using"
  → "ok" 출력되면 정상

### 배포 주의사항

코드 변경 후 반드시 deploy.sh로 배포한다:
  bash scripts/deploy.sh

⚠️ 배포 후 "최신 빌드 아님" 현상이 발생하면 구 프로세스가 포트를 점유하고 있는 것이다.
   deploy.sh가 ss 기반으로 강제 종료하도록 수정됨 (2026-04-20).
   문제가 반복될 경우 수동 복구:
     ss -tlnp | grep 3000   # 점유 PID 확인
     kill -9 [PID]
     bash scripts/deploy.sh

### 절대 금지
- 직접 코드 작성
- 소스코드를 프롬프트에 포함
- CLI 실행 없이 프롬프트만 생성하고 대기

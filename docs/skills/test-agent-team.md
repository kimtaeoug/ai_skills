# test-agent-team

대상 저장소가 이미 가진 lint, 타입검사, 테스트, 빌드, UI 검사를 안전한 순서로 실행하고 결과를 하나의 상태 체계로 보고하는 테스트 워크플로다. 새 테스트 도구를 설치하거나 기존 도구를 자동 교체하지 않는다.

## 호출

Claude에서는 자연어로 요청한다.

```text
테스트 팀 돌려줘: /path/to/repository
```

Codex에서는 명시 호출도 가능하다.

```text
$test-agent-team 이 레포의 lint, 타입체크, 테스트, 빌드와 화면 테스트를 실행해줘
```

다른 트리거는 `이 레포 테스트/린트/타입체크 다 돌려줘`, `화면 테스트까지 포함해서 테스트해줘`, `run the test team`이다.

## 사용 방법

대상 경로와 원하는 검사 범위를 함께 주면 된다.

```text
$test-agent-team packages/api와 packages/web의 기존 검사만 실행해줘. UI는 web 패키지에만 적용해줘.
```

지갑 연결이 필요한 dApp은 테스트 계정 여부를 먼저 확인해야 한다.

```text
$test-agent-team 이 dApp의 지갑 연결 UI를 testnet burner 지갑으로만 확인해줘
```

mainnet 또는 실자산 계정은 이 스킬의 범위 밖이며 `blocked`로 처리한다.

## 실행 흐름

1. 대상 경로, Git 상태 기준선, 모노레포 경계를 확인한다.
2. package script, CI, Makefile 등에서 실제로 쓰는 검사 명령을 찾는다.
3. 서로 같은 산출물·포트·DB를 공유하지 않는 lint, 타입검사, 테스트, 빌드만 병렬 실행한다.
4. 병렬 검사가 끝난 뒤 UI 검사는 단일 lane에서 직렬 실행한다.
5. 시작한 dev server PID만 종료하고, Git 상태 기준선과 비교해 부작용을 보고한다.

실행은 읽기 전용이다. `--fix`, `--write`, snapshot update, migration, seed와 자동 install은 실행하지 않는다. 비밀 환경변수나 배포 자격증명도 스크립트에 넘기지 않는다.

## UI·지갑 테스트 제약

UI 검사는 Playwright 또는 저장소의 기존 도구를 우선 사용하며, 병렬 그룹과 동시에 실행하지 않는다. 지갑 확장 UI는 실제 무자산 testnet/dev burner 전용이다.

계정 선택, 네트워크 전환, 서명, permit, approval, send/swap/bridge 등은 사람이 직접 승인해야 한다. seed phrase, 개인키, 비밀번호, QR, 지갑 팝업의 민감한 화면을 수집·로그·공유하지 않는다.

## 결과

각 검사는 다음 중 하나로 보고한다.

- `pass`: 실행되어 통과
- `fail`: 실행되어 실패
- `blocked`: 실행 불가
- `not-applicable`: 해당 검사가 원래 없음
- `not-found`: 있어야 할 검사 도구를 찾지 못함

실패는 기본적으로 재시도하지 않으며, 한 번 재실행해 통과한 경우에도 원래 실패를 숨기지 않고 `flaky-suspected`로 남긴다. 최종 보고에는 실제 명령, 핵심 실패 로그, 스킵·차단 이유, 패키지별 결과, 검사 후 Git 상태 차이가 포함된다.

전체 안전 규칙과 도구 탐지 순서는 [원본 스킬 정의](../../.claude/skills/test-agent-team/SKILL.md)를 따른다.

# Evolve

실사용 중 변경된 스킬의 baseline 대비 차이와 검증 근거를 기록하는 스킬이다. 공용 원본은 `.agents/skills/evolve/SKILL.md`이며 Claude와 Codex 진입점은 이 원본을 참조한다.

## 설치

```bash
bin/install-evolve
```

설치기는 세 런타임 스킬 경로에 공용 원본 링크를 만들고, 기존 Claude 설정을 보존하면서 `PostToolUse`와 `Stop` 훅을 한 번씩 등록한다. 다른 파일이나 디렉터리가 같은 위치에 있으면 덮어쓰지 않고 종료한다.

## 사용법

- `/evolve`
- `이 스킬 진화 기록해줘`
- `record this skill's evolution`

대상 스킬의 baseline이 없다면 먼저 snapshot 생성 여부를 확인한다. 변경이 있으면 context, delta, evidence와 재사용 가능한 교훈을 `evolution/records/`에 기록한다. baseline 갱신과 lesson 승격은 항상 사용자 승인이 필요하다.

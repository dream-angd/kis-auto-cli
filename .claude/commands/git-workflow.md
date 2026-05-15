# Git Workflow

KIS Auto CLI 프로젝트 전용 Git 워크플로우.
CONTRIBUTING.md의 커밋 컨벤션, 브랜치 전략, 버전 관리 규칙을 자동으로 적용한다.

## User Input
$ARGUMENTS

## 프로젝트 설정

| 항목 | 값 |
|------|-----|
| 프로젝트명 | KIS_AUTO_CLI |
| 메인 브랜치 | master |
| 버전 파일 | ./VERSION |
| 태그 형식 | v{version} |

## Core Principles

1. **Phase 1 변경 분석 결과는 반드시 사용자 확인** — 변경 파일 목록을 검토받아야 한다.
2. **버전 업데이트는 feature 브랜치에서 develop 머지 직전에만** — 커밋 단계에서 VERSION 파일을 수정하지 않는다.
3. **변경사항이 없으면 즉시 종료** — 빈 커밋을 만들지 않는다.
4. **push는 Claude가 직접 실행하지 않는다** — 사용자가 명시적으로 요청할 때만 예외.
5. **버전 증가는 commit type 기준** — feat → MINOR, 그 외 → PATCH.
6. **develop이 기본 작업 브랜치** — feature/bugfix는 develop에서 분기, develop으로 머지. master는 사용자 명시 요청 시에만.

## Worktree Flow (변경사항 없을 때 새 작업 시작)

`git status --porcelain` 결과가 비어 있고, 사용자 요청에 브랜치/작업 시작 의도가 있으면 아래 Flow W를 실행하고 종료한다.

### Flow W: 브랜치 생성

**W-1. 브랜치명 결정**

| commit type 의도 | prefix |
|----------------|--------|
| feat / refactor / docs / chore | `feature/` |
| fix | `bugfix/` |

형식: `{prefix}/{간략한-설명}` (소문자·하이픈, 단어 3개 이하)

**W-2. 실행**

```bash
git checkout develop
git checkout -b {브랜치명}
```

**W-3. 완료 출력**

```
🌿 브랜치 생성 완료

[브랜치] {브랜치명}

해당 브랜치에서 작업 후 /git-workflow를 실행하면 커밋·머지까지 처리됩니다.
```

---

## Workflow 실행 순서

refs 폴더: `.claude/refs/git-workflow/`

Phase 1(phase1-change-analysis.md) → Phase 2(phase2-branch-commit.md) → Phase 3(phase3-version-merge.md) → Phase 4(phase4-cleanup.md) 순서로 실행.
각 Phase 파일은 해당 단계 시작 시에만 읽는다. 단계를 건너뛰지 않는다.

## 사용 예시

```
/git-workflow
/git-workflow v1.2.0
```

# Phase 1 — 변경 분석

## Safety Gates (절대 건너뛰지 않는다)
- ⛔ 블록된 브랜치 감지 즉시 중단 (Step 2)
- ⛔ 변경 요약 출력 후 반드시 사용자 Y 대기 (Step 5)
- ⛔ 코드 리뷰 REJECT 판정 시 Phase 2로 진행 금지 (Step 6)

## 역할
변경 파일 분석 → 커밋 타입 분류 → 사용자 확인 → 코드 리뷰(조건부)

---

## Step 1: 변경 파일 확인

```bash
git status
```

변경사항이 없으면 즉시 종료:
```
변경된 파일이 없습니다. 워크플로우를 종료합니다.
```

---

## Step 2: 현재 브랜치 확인

```bash
git branch --show-current
```

**블록된 브랜치:**

| 브랜치 | 이유 |
|--------|------|
| master | 릴리즈 전용. 직접 커밋 불가 |

블록된 브랜치에서 실행 시 즉시 중단:
```
⛔ '{브랜치명}'은 보호된 브랜치입니다. git-workflow를 실행할 수 없습니다.
develop 브랜치로 이동 후 다시 실행하세요.
```

**브랜치별 처리:**

- **develop** → 정상 (Phase 2에서 feature 브랜치 생성)
- **feature/* 또는 bugfix/*** → 사용자에게 확인:
  ```
  현재 '{브랜치명}' 브랜치에 있습니다.
  1. 이 브랜치에서 계속 진행
  2. develop으로 돌아가서 새 브랜치 생성

  선택 (1/2):
  ```
- **그 외** → 경고 후 동일하게 선택지 제공

---

## Step 3: develop 브랜치 자동 설정 (develop에 있을 때)

develop 브랜치가 master보다 뒤처져 있는 경우 자동 동기화:

```bash
git log develop..master --oneline
```

- 뒤처진 경우:
  ```bash
  git merge master --no-ff -m "merge: master → develop 동기화"
  ```
  ```
  ℹ️ develop이 master보다 뒤처져 있어 자동 동기화했습니다.
  ```
- 동일한 경우 → 그대로 진행

---

## Step 4: 커밋 타입 자동 분류

변경 파일과 내용을 분석해 commit type을 결정한다.

| type | 조건 |
|------|------|
| feat | 새 기능 추가 |
| fix | 버그 수정 |
| refactor | 기능 변화 없는 코드 개선 |
| docs | 문서 업데이트 |
| chore | 빌드, 설정, 의존성 변경 |

분류 불명확 시: `chore`로 fallback하고 변경 요약에 분류 근거를 명시한다.

---

## Step 5: 변경 요약 출력 및 사용자 확인

아래 형식으로 출력하고 반드시 대기한다:

```
📋 변경 분석 결과

[프로젝트] KIS_AUTO_CLI
[commit type] feat / fix / refactor / docs / chore
[분류 근거] {한 줄 설명}

[변경 파일]
  수정: src/trader.py
  추가: src/new_feature.py
  삭제: (없음)

진행하시겠습니까? (Y/N)
```

> ⚠️ 이 단계가 변경 범위를 확정하는 마지막 지점입니다.
> 관련 파일이 누락되었다면 지금 추가하세요.
> 머지 완료 후 추가 변경은 새 /git-workflow로만 처리 가능합니다.

⛔ 사용자가 Y를 입력하기 전에 Phase 2로 진행하지 않는다.
N 입력 시 워크플로우 종료.
commit type에 이견이 있으면 사용자 의견을 따른다.

---

## Step 6: 코드 리뷰 (조건부 자동 실행)

commit type과 변경 파일을 기준으로 리뷰 필요 여부를 자동 판단한다. 사용자에게 묻지 않는다.

| 조건 | 판단 |
|------|------|
| `feat` 또는 `fix` | ✅ 리뷰 필요 |
| `refactor`이고 `.py` 소스 파일 포함 | ✅ 리뷰 필요 |
| `docs`, `chore` | ⏭️ 스킵 |
| `refactor`이고 `.md`, `.txt`, `.json`, `.yaml` 만 변경 | ⏭️ 스킵 |

**스킵 시:**
```
ℹ️ 코드 리뷰 스킵 (commit type: {type}, 실행 가능한 코드 변경 없음)
```

**리뷰 필요 시 — 인라인 리뷰 실행:**

```bash
git diff
git diff --cached
```

diff를 분석해 아래 4가지 관점에서 검토한다:
1. **품질** — 네이밍, 가독성, 중복
2. **로직** — 엣지케이스, 조건 누락, 잘못된 계산
3. **보안** — API 키 노출, 입력 검증, 인젝션 위험
4. **성능** — 불필요한 루프, 블로킹 호출, 메모리 낭비

**판정 기준:**

| 판정 | 조건 | 다음 단계 |
|------|------|----------|
| ✅ PASS | Critical 0건, Warning ≤ 3건 | Phase 1 Output으로 진행 |
| ⚠️ REVIEW_NEEDED | Critical 0건, Warning ≥ 4건 | 사용자 확인 후 진행 |
| ❌ REJECT | Critical ≥ 1건 | 워크플로우 중단, 수정 요청 |

**REVIEW_NEEDED 시:**
```
⚠️ Warning {N}건 발견.

주요 Warning:
1. {파일}:{라인} - {설명}

그래도 커밋하시겠습니까? (Y/N)
```

**REJECT 시:**
```
❌ Critical {N}건 발견 — 커밋할 수 없습니다.

즉시 수정 필요:
1. {파일}:{라인} - {설명}

수정 후 /git-workflow를 다시 실행하세요.
```

---

## Phase 1 Output (Phase 2 입력값)

```
[변경 분석]
프로젝트: KIS_AUTO_CLI
commit type: feat / fix / refactor / docs / chore
변경 파일 목록: {파일 목록}
변경 요약: {한 줄 설명}
현재 브랜치: {브랜치명}
브랜치 전략: 새 브랜치 생성 / 현재 브랜치 유지
```

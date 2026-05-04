# Phase 3 — 버전 업데이트 + 머지

## 역할
develop에서 squash merge로 feature 브랜치를 단일 커밋으로 합치고,
VERSION bump를 포함해 커밋한 뒤 태그를 생성한다.

---

## Step 0: Phase 2 Output 검증

**필수 필드:**
- 브랜치명 (현재 feature/bugfix 브랜치)
- 커밋 해시
- 커밋 메시지 (subject + body)
- commit type

누락 필드가 있으면 즉시 중단:
```
⚠️ Phase 2 커밋 데이터가 불완전합니다.
누락 필드: {누락 필드 목록}

처음부터 다시 실행해주세요.
```

---

## Step 1: 새 버전 계산

`./VERSION` 파일에서 현재 버전을 읽는다. 파일 내용이 그대로 버전 번호다 (예: `1.3.2`).

**사용자가 버전을 직접 지정한 경우 ($ARGUMENTS에 버전 포함):**
자동 계산을 건너뛰고 지정값을 그대로 사용한다.

**자동 계산:**

| commit type | 변화 | 예시 |
|-------------|------|------|
| feat | MINOR +1, PATCH = 0 | 1.3.2 → 1.4.0 |
| fix / refactor / docs / chore | PATCH +1 | 1.3.2 → 1.3.3 |

⚠️ MAJOR는 자동 증가하지 않는다. 사용자가 직접 지정해야 한다.

**버전 계산 자가 검증 (진행 전 필수):**
- [ ] `x.y.z` 형식 (모두 정수)
- [ ] `feat` 타입: MINOR +1, PATCH = 0 (이전 PATCH 값과 무관하게 0으로 리셋)
- [ ] 그 외 타입: PATCH +1만, MINOR 변화 없음
- [ ] 새 버전 > 이전 버전 (버전 감소 불가)
- [ ] MAJOR는 사용자 지정 없이 자동 증가 없음

---

## Step 2: develop으로 이동 + Squash Merge

```bash
git checkout develop

# squash merge: feature 브랜치 커밋을 staged 상태로 합침 (커밋 없음)
git merge --squash {feature 브랜치명}
```

**충돌 발생 시:**
```
⚠️ 머지 충돌이 발생했습니다.

충돌 파일:
  - {파일 목록}

해결 방법:
  1. 충돌 파일의 <<<<<<< / ======= / >>>>>>> 마커를 확인하고 수동으로 수정
  2. 해결 완료 후 "continue"라고 입력

또는:
  - "abort" → git merge --abort 실행 후 feature 브랜치로 복귀
```

---

## Step 3: VERSION bump 포함 단일 커밋

squash 후 VERSION bump를 staged에 추가하고, feature 브랜치의 커밋 메시지를 재사용해 단일 커밋으로 기록한다.

```bash
# VERSION 파일 업데이트
echo "{새 버전}" > VERSION

# ⛔ git add -A 절대 금지 — 변경된 파일만 명시적으로 추가
git add {squash로 올라온 파일 목록} VERSION

# feature 브랜치 커밋 메시지(subject + body) 그대로 재사용
git commit -m "$(cat <<'EOF'
{feature 브랜치 커밋 메시지 전체}
EOF
)"
```

---

## Step 4: 태그 생성

```bash
git tag -a v{새 버전} -m "release: v{새 버전}"
```

**태그가 이미 존재하는 경우:**
```
⚠️ 태그 v{새 버전}이 이미 존재합니다.

1. 다음 버전으로 증가 (v{대안 버전})
2. 기존 태그 덮어쓰기 (권장하지 않음)
3. 워크플로우 중단

선택 (1/2/3):
```

---

## Step 5: master 릴리즈 머지 (사용자 명시 요청 시에만)

"master에 머지", "릴리즈 머지", "master 반영" 등 명시적 요청이 있을 때만 실행한다.
일반 워크플로우에서는 이 단계를 건너뛰고 완료 출력으로 진행한다.

### 5-1. MAJOR 버전 계산

현재 버전에서 MAJOR +1, MINOR = 0, PATCH = 0.
```
예: 0.5.3 → 1.0.0
```

사용자가 버전을 직접 지정한 경우 그 값을 사용한다.

### 5-2. develop에서 VERSION 수정 + 커밋

```bash
echo "{새 MAJOR 버전}" > VERSION
git add VERSION
git commit -m "chore: bump version to v{새 MAJOR 버전}"
```

### 5-3. master로 머지

```bash
git checkout master
git merge develop --no-ff -m "release: v{새 MAJOR 버전} - merge develop into master"
```

### 5-4. 릴리즈 태그 생성

```bash
git tag -a v{새 MAJOR 버전} -m "release: v{새 MAJOR 버전}"
```

### 5-5. develop으로 복귀

```bash
git checkout develop
```

---

## 완료 출력

**develop squash 머지 (일반):**
```
✅ squash 머지 + 버전 업데이트 완료

{이전 버전} → {새 버전}
태그: v{새 버전}

정리 단계로 진행합니다.
```

**master 릴리즈 머지 포함 시:**
```
✅ squash 머지 + master 릴리즈 머지 완료

develop 버전: {이전 버전} → {새 버전}
릴리즈 버전: {새 버전} → v{새 MAJOR 버전}
태그: v{새 버전} (develop), v{새 MAJOR 버전} (릴리즈)

정리 단계로 진행합니다.
```

---

## 실패 처리

| 명령어 | 최대 재시도 | 재시도 조건 | 재시도 불가 시 |
|--------|-----------|-----------|-------------|
| VERSION 파일 읽기 | 2 | IO 오류 → 경로 재확인 후 재시도 | 파일 경로와 오류를 사용자에게 보고 |
| VERSION 파일 쓰기 | 1 | IO 오류 → 재시도 | 파일 경로와 오류를 사용자에게 보고 |
| `git merge --squash` (충돌) | 0 | 재시도 없음 — 사용자 수동 해결 필요 | 충돌 파일 목록 제공 |
| `git merge --squash` (기타) | 1 | 충돌 외 오류 → 재시도 | abort 후 사용자에게 보고 |
| `git commit` | 1 | pre-commit hook 실패 → 수정 후 재시도 | 사용자에게 보고 |
| `git tag` (이미 존재) | 1 | PATCH+1 후 재시도 | 사용자에게 버전 확인 요청 |

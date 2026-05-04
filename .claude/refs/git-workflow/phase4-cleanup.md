# Phase 4 — 정리 + 완료 리포트

## 역할
feature 브랜치를 삭제하고 완료 리포트를 출력한다.

---

## Step 1: feature 브랜치 삭제

squash merge는 git이 "fully merged"로 인식하지 않으므로 강제 삭제를 사용한다.

```bash
git branch -D {feature 브랜치명}
```

---

## Step 2: 완료 리포트

**develop squash 머지 (일반):**
```
════════════════════════════════════════
✅ 워크플로우 완료
════════════════════════════════════════

[프로젝트] KIS_AUTO_CLI
[버전]     {이전 버전} → {새 버전}
[변경]     {커밋 메시지 제목}
[머지]     {feature 브랜치명} → develop (squash, 브랜치 삭제됨)
[태그]     v{새 버전} 생성됨

────────────────────────────────────────
⛔ push 시 태그를 반드시 포함하세요

CLI:
  git push origin develop
  git push origin v{새 버전}

또는:
  git push origin develop --tags

────────────────────────────────────────
⛔ 추가 변경사항은 반드시 새 /git-workflow로 처리하세요.
   develop에 직접 커밋하지 마세요.
────────────────────────────────────────
```

**master 릴리즈 머지 포함 시:**
```
════════════════════════════════════════
✅ 워크플로우 완료 (릴리즈 머지 포함)
════════════════════════════════════════

[프로젝트] KIS_AUTO_CLI
[develop 버전] {이전 버전} → {새 버전}
[릴리즈 버전] {새 버전} → v{새 MAJOR 버전}
[변경]     {커밋 메시지 제목}
[머지]     {feature 브랜치명} → develop → master (squash, 브랜치 삭제됨)
[태그]     v{새 버전} (develop), v{새 MAJOR 버전} (릴리즈)

────────────────────────────────────────
⛔ push 시 태그를 반드시 포함하세요

CLI:
  git push origin develop master
  git push origin v{새 버전} v{새 MAJOR 버전}

또는:
  git push origin develop master --tags

────────────────────────────────────────
```

---

## Push 규칙

**기본 동작:** Claude는 push를 자동으로 실행하지 않는다. 완료 리포트에 명령어를 안내한다.

**예외:** 사용자가 명시적으로 push를 요청한 경우 즉시 실행한다.

명시적 push 요청 예시: "push해줘", "푸시해줘", "push까지 해줘", "push도 해줘"

```bash
# develop + 태그
git push origin develop
git push origin v{새 버전}

# master 릴리즈 머지 포함 시
git push origin develop master
git push origin v{새 버전} v{새 MAJOR 버전}
```

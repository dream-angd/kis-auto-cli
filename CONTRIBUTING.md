# Contributing Guide

## 커밋 컨벤션

### 형식

```
{type}: {한국어 설명}

{body}
```

- `type`은 영어, 설명은 한국어 (클래스명·메서드명·파일명 등 기술 용어 제외)
- body는 모든 타입에서 필수

### 타입

| type | 설명 |
|------|------|
| feat | 새 기능 추가 |
| fix | 버그 수정 |
| refactor | 리팩토링 |
| docs | 문서 업데이트 |
| chore | 빌드, 설정 변경 |
| merge | 브랜치 병합 |

### Body 작성 규칙

변경의 **이유**와 **영향 범위**를 설명한다.

- 변경의 근본 원인 또는 동기
- 기존 동작 vs 새 동작
- 영향 범위 (파일, 함수, 모듈)
- 제목과 본문 사이에 빈 줄 하나

```
fix: 세션 만료 후 자동 로그아웃 처리

토큰 갱신 실패 시 예외가 무시되어 만료된 세션이 유지됨.
이후 API 호출에서 401 오류가 연속 발생.

수정: 토큰 갱신 실패 시 즉시 로그아웃 처리 후 로그인 화면으로
이동. AuthInterceptor에서 refresh 실패 케이스 추가.
```

---

## 브랜치 전략

Git Flow 기반 전략을 사용한다.

```
master          ← 릴리즈 전용 (명시적 요청 시에만 머지)
  └─ develop    ← 기본 작업 브랜치
       ├─ feature/{description}   ← feat / refactor / docs / chore
       └─ bugfix/{description}    ← fix
```

### 브랜치 이름 규칙

- 소문자·숫자·하이픈만 사용
- 형식: `{prefix}/{간략한-설명}` (단어 3개 이하)

| commit type | prefix |
|-------------|--------|
| feat / refactor / docs / chore | `feature/` |
| fix | `bugfix/` |

### 머지 규칙

- feature/bugfix → develop: `--no-ff` 머지
- develop → master: 릴리즈 시에만, 사용자가 명시적으로 요청할 때

---

## 버전 관리

`MAJOR.MINOR.PATCH` 체계를 사용하며 `VERSION` 파일로 관리한다.

| commit type | 변화 |
|-------------|------|
| feat | MINOR +1, PATCH = 0 |
| fix / refactor / docs / chore | PATCH +1 |

- **MAJOR**는 자동 증가 없음 — 직접 지정
- 버전 업데이트는 feature/bugfix 브랜치에서 develop 머지 직전에 수행
- 태그 형식: `v{version}` (예: `v1.2.3`)

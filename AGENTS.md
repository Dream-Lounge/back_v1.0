# Dream Lounge — 백엔드 개발 컨텍스트

## 프로젝트 개요

청주대학교 동아리 관리 시스템 웹 플랫폼의 **백엔드 서버**.
프론트엔드는 별도 레포에서 관리하며, 이 레포는 REST API 서버만 담당한다.
프론트에서 `https://api.dreamlounge.com/api/v1/...` 형태로 요청을 보내면
`routers/v1/` 안의 파일들이 응답을 처리한다.

---

## 기술 스택

- **언어/프레임워크**: Python, FastAPI
- **패키지 관리**: uv
- **ORM**: SQLAlchemy + Alembic (마이그레이션)
- **DB**: Supabase (PostgreSQL 호스팅)
- **인증**: JWT (로그인 시 토큰 발급)
- **개발 환경**: macOS, VS Code, Claude Code

---

## 파일 구조 및 각 폴더 역할

```
dreamlounge-backend/
│
├── app/
│   ├── main.py                  # FastAPI 앱 생성, 모든 라우터 등록, CORS 설정
│   │
│   ├── core/                    # 앱 전역 설정 모음
│   │   ├── config.py            # .env 파일의 환경변수를 파이썬 객체로 불러옴
│   │   ├── security.py          # JWT 토큰 생성·검증, 비밀번호 해싱(bcrypt)
│   │   └── dependencies.py      # 로그인 여부 확인, 권한 체크 등 공통 의존성 함수
│   │
│   ├── db/                      # 데이터베이스 연결 설정
│   │   ├── base.py              # SQLAlchemy Base 클래스, engine 생성
│   │   └── session.py           # 요청마다 DB 세션을 열고 닫는 get_db() 함수
│   │
│   ├── models/                  # ORM 모델 — DB 테이블 구조를 파이썬 클래스로 정의
│   │   ├── user.py              # users, privacy_consents 테이블
│   │   ├── club.py              # clubs, club_tags 테이블
│   │   ├── club_member.py       # club_members 테이블 (부원 목록, 역할, 상태)
│   │   ├── application.py       # application_forms, form_questions,
│   │   │                        # applications, application_answers 테이블
│   │   ├── post.py              # posts, comments 테이블
│   │   └── notification.py      # notifications 테이블
│   │
│   ├── schemas/                 # Pydantic 스키마 — API 요청/응답의 데이터 형태 정의
│   │   ├── user.py              # 회원가입 요청, 로그인 응답, 유저 정보 응답 등
│   │   ├── club.py              # 동아리 등록 요청, 동아리 상세 응답 등
│   │   ├── application.py       # 신청서 작성 요청, 임시저장 요청, 심사 결과 응답 등
│   │   ├── post.py              # 게시글/댓글 작성 요청, 목록 응답 등
│   │   └── notification.py      # 알림 응답 형태
│   │
│   ├── routers/                 # 프론트와 통신하는 API 엔드포인트 모음
│   │   └── v1/                  # /api/v1/ 경로로 묶임 — 나중에 v2로 확장 가능
│   │       ├── router.py        # v1 하위 모든 라우터를 한 곳에 등록
│   │       ├── auth.py          # 회원가입, 로그인, 이메일 인증
│   │       ├── clubs.py         # 동아리 CRUD, 검색
│   │       ├── applications.py  # 신청서 임시저장, 제출, 심사
│   │       ├── members.py       # 동아리 회원 관리, 권한 이전
│   │       ├── posts.py         # 게시판 게시글/댓글 CRUD
│   │       └── notifications.py # 알림 조회 및 읽음 처리
│   │
│   ├── services/                # 비즈니스 로직 — 실제 처리 코드는 여기에만 작성
│   │   ├── auth_service.py      # 이메일 인증번호 검증, 회원가입 처리, 토큰 발급
│   │   ├── club_service.py      # 동아리 생성·수정·검색, 회장 권한 확인
│   │   ├── application_service.py # 임시저장·제출·심사 상태 변경 처리
│   │   ├── post_service.py      # 게시글 공지 설정, 삭제 권한 확인
│   │   └── notification_service.py # 알림 생성·발송 (합격/공지 시 트리거)
│   │
│   └── utils/
│       ├── email.py             # 청주대 이메일로 인증번호 발송
│       └── pagination.py        # 목록 API 공통 페이지네이션 유틸
│
├── alembic/                     # DB 마이그레이션 — 테이블 변경 이력 추적
│   ├── env.py
│   └── versions/                # 마이그레이션 파일들이 날짜순으로 쌓임
│
├── tests/
│   ├── conftest.py              # 테스트용 DB 세션, 테스트 클라이언트 설정
│   ├── test_auth.py
│   ├── test_clubs.py
│   └── test_applications.py
│
├── .env                         # 실제 환경변수 (DB URL, JWT 시크릿 등) — gitignore 필수
├── .env.example                 # 팀원 공유용 환경변수 예시
├── alembic.ini
├── pyproject.toml               # uv로 관리하는 패키지 목록
└── CLAUDE.md                    # 이 파일 — Claude Code가 매 대화마다 자동으로 읽음
```

---

## 개발 규칙

- **비즈니스 로직 분리**: 모든 처리 코드는 `services/`에 작성. `routers/`는 요청 수신과 응답 반환만 담당
- **환경변수**: `.env`에서만 관리. 코드에 URL, 시크릿 키 등 하드코딩 절대 금지
- **DB 변경**: 반드시 Alembic 마이그레이션으로 관리. 직접 테이블 수정 금지
- **응답 형태**: `schemas/`의 Pydantic 모델로 통일
- **API 버전**: 모든 엔드포인트는 `/api/v1/` 접두사 사용

---

## 사용자 권한 구조

| 권한 | 설명 | 획득 조건 |
|---|---|---|
| 비회원 | 동아리 목록/상세 조회, 검색만 가능 | 기본 |
| 신청자 (일반회원) | 동아리 신청서 작성·제출·임시저장, 마이페이지 사용 | 회원가입 완료 |
| 부원 | 동아리 게시판 열람, 게시글·댓글 작성 | 동아리 합격 후 |
| 관리자 (동아리 회장) | 게시판 공지 설정·삭제, 신청서 심사, 회원 관리, 권한 이전 | 동아리 직접 등록 시 |

- `CLUB_MEMBER.role`: `president` / `member`
- `CLUB_MEMBER.status`: `active` / `withdrawn`
- 동아리 회장도 부원이므로 부원 기능을 모두 사용할 수 있음
- 이미 등록된 동아리를 다른 사람이 중복 등록할 수 없음

---

## 전체 서비스 흐름

### 웹사이트 첫 진입
- 비회원도 메인 화면의 동아리 소개글, 동아리 검색 기능 사용 가능
- 동아리 신청, 마이페이지 접근 시도 시 → 회원가입 페이지로 리다이렉트

### 회원가입 흐름
1. [회원가입] 버튼 클릭 → **개인정보 수집 동의 화면** 먼저 표시
   - 필수 항목 미동의 시 가입 진행 불가
   - 동의 완료 후 정보 입력 페이지로 이동
2. 입력 항목: 학번, 비밀번호, 이름, 전화번호, 학과, 청주대학교 이메일
3. 이메일 인증번호 발송 → 인증번호 입력 확인 → 회원가입 완료
4. 로그인 화면으로 이동
- **로그인**: 학번 + 비밀번호

---

## 신청자 기능 상세

### 동아리 신청서 작성
- 동아리 상세페이지의 [신청하기] 버튼 클릭 → 해당 동아리의 신청서 페이지 이동
- 신청서 페이지 내 버튼: **[임시저장]**, **[제출하기]**
  - [임시저장] → `APPLICATION.is_draft: true` 로 저장 → 마이페이지 임시저장함에 보관
  - [제출하기] → `APPLICATION.is_draft: false` 로 저장 → 마이페이지 나의 신청서에 보관

### 마이페이지 구성

**임시저장함**
- 임시저장한 신청서 리스트 표시
- 항목 클릭 → 상세 수정 페이지 (수정 가능)
- 상세 수정 페이지 버튼:
  - [저장하기]: 수정사항 저장, 임시저장함에 그대로 유지
  - [제출하기]: 수정사항 반영 후 최종 제출 → 나의 신청서로 이동

**나의 신청서**
- 제출한 신청서 리스트 표시
- 항목 클릭 → 제출한 내용 확인 (수정 불가, 읽기 전용)
- 각 항목 우측에 현재 상태 표시: `대기중` / `보류(1차합격)` / `합격` / `불합격`

**나의 기록**
- 내가 동아리 게시판에 작성한 게시글·댓글 목록
- 해당 글 클릭 시 수정 및 삭제 가능

**활동중인 동아리**
- 합격된 동아리의 게시판으로 이동하는 링크 목록
- 동아리 게시판에서 게시글·댓글 작성 가능
- 부원이 작성하는 게시글은 일반 글로 분류

**나의 동아리**
- 본인이 직접 등록한 동아리 (관리자 전용)
- 신청자는 이 칸이 비어 있음
- [동아리 등록하기] 버튼 존재 → 클릭 시 관리자가 됨

---

## 관리자(동아리 회장) 기능 상세

### 동아리 등록 (상세페이지 관리)
마이페이지 → 나의 동아리 → [동아리 등록하기] 클릭 시 등록 페이지 진입.
등록한 정보는 동아리 상세페이지에 표시됨.

등록 항목:
- 연락망: 이메일, 오픈채팅 링크, 전화번호 (텍스트 입력)
- 동아리 분류: 학과 동아리 / 중앙 동아리 (라디오 버튼)
- 동아리 이름, 상세 설명, 활동 이미지
- 태그 설정: 분과, 분야, 분위기, 동아리 활동 목적, 주 활동 기간, 모집기간

### 동아리 게시판 관리
- 관리자가 작성하는 글은 자동으로 `[공지]` 처리 → 부원 전체에게 알림 발송
- 일반 글을 `[공지]`로 전환 가능 → 전환 시에도 부원 전체 알림
- 모든 게시글 삭제 권한 보유

### 동아리 회원 관리
- 회원 명단 조회: 이름, 학번, 학년, 학과, 이메일, 전화번호
- 각 명단 우측 버튼:
  - **탈퇴**: 회원이 탈퇴 신청 시 명단에서 삭제, DB 권한 수정
  - **권한 이전**: 해당 부원에게 회장 권한 부여 → 기존 회장은 일반 부원으로 강등

### 동아리 신청 폼 관리
- 구글폼처럼 신청서 질문을 직접 커스텀 (추가/수정/삭제/순서 변경)

### 동아리 신청서 관리
- 제출된 신청서 리스트 조회
- 신청서 상세 확인 후 상태 선택:
  - `보류`: 1차 합격, 면접 안내는 전화번호로 직접 연락
  - `합격`: 최종 합격 → 해당 학번이 동아리 부원으로 등록됨
  - `불합격`
- 상태 변경 시 신청자에게 알림 발송

---

## DB 설계

### 핵심 상태값

| 테이블 | 컬럼 | 값 |
|---|---|---|
| APPLICATION | is_draft | true=임시저장, false=제출 |
| APPLICATION | status | `draft` / `submitted` / `pending` / `passed` / `failed` |
| CLUB_MEMBER | role | `president` / `member` |
| CLUB_MEMBER | status | `active` / `withdrawn` |
| POST | is_notice | true=공지, false=일반 |
| POST | post_type | `notice` / `general` |
| NOTIFICATION | noti_type | `application_result` / `new_notice` |

### ERD (Mermaid)

```
erDiagram
  USER {
    uuid id PK
    string student_id UK
    string password_hash
    string name
    string phone
    string department
    string email UK
    bool email_verified
    bool is_active
    timestamp created_at
    timestamp updated_at
  }

  PRIVACY_CONSENT {
    uuid id PK
    uuid user_id FK
    bool required_agreed
    bool optional_agreed
    timestamp agreed_at
  }

  CLUB {
    uuid id PK
    uuid president_id FK
    string name UK
    string club_type
    string description
    string contact_email
    string contact_phone
    string open_chat_url
    string image_url
    string division
    string field
    string atmosphere
    string activity_purpose
    string activity_period
    date recruit_start
    date recruit_end
    bool is_recruiting
    timestamp created_at
    timestamp updated_at
  }

  CLUB_TAG {
    uuid id PK
    uuid club_id FK
    string tag_key
    string tag_value
  }

  CLUB_MEMBER {
    uuid id PK
    uuid club_id FK
    uuid user_id FK
    string role
    string status
    timestamp joined_at
    timestamp left_at
  }

  APPLICATION_FORM {
    uuid id PK
    uuid club_id FK
    string title
    bool is_active
    timestamp created_at
    timestamp updated_at
  }

  FORM_QUESTION {
    uuid id PK
    uuid form_id FK
    string question_text
    string question_type
    bool is_required
    int order_index
    json options
  }

  APPLICATION {
    uuid id PK
    uuid form_id FK
    uuid user_id FK
    string status
    bool is_draft
    timestamp submitted_at
    timestamp updated_at
  }

  APPLICATION_ANSWER {
    uuid id PK
    uuid application_id FK
    uuid question_id FK
    text answer_text
  }

  POST {
    uuid id PK
    uuid club_id FK
    uuid author_id FK
    string post_type
    string title
    text content
    bool is_notice
    bool is_deleted
    timestamp created_at
    timestamp updated_at
  }

  COMMENT {
    uuid id PK
    uuid post_id FK
    uuid author_id FK
    text content
    bool is_deleted
    timestamp created_at
    timestamp updated_at
  }

  NOTIFICATION {
    uuid id PK
    uuid recipient_id FK
    string noti_type
    string message
    json payload
    bool is_read
    timestamp created_at
  }

  USER ||--o{ PRIVACY_CONSENT : "동의"
  USER ||--o{ CLUB : "운영(회장)"
  USER ||--o{ CLUB_MEMBER : "소속"
  CLUB ||--o{ CLUB_MEMBER : "포함"
  CLUB ||--o{ CLUB_TAG : "태그"
  CLUB ||--o{ APPLICATION_FORM : "신청폼"
  APPLICATION_FORM ||--o{ FORM_QUESTION : "질문"
  APPLICATION_FORM ||--o{ APPLICATION : "신청서"
  APPLICATION ||--o{ APPLICATION_ANSWER : "답변"
  USER ||--o{ APPLICATION : "작성"
  CLUB ||--o{ POST : "게시글"
  USER ||--o{ POST : "작성"
  POST ||--o{ COMMENT : "댓글"
  USER ||--o{ COMMENT : "작성"
  USER ||--o{ NOTIFICATION : "수신"
```

---

## 현재 개발 범위 (MVP)

아래 기능만 먼저 개발한다. 이외 기능은 MVP 완료 후 진행.

### 개발 순서
1. **인증** — 회원가입, 이메일 인증, 로그인 (JWT 발급)
2. **동아리 조회** — 상세 조회 (임시 데이터 1개로 테스트)
3. **신청서** — 임시저장, 제출
4. **임시저장함** — 목록 조회, 상세 조회, 수정, 제출
5. **나의 신청서** — 제출 내역 목록 조회, 상세 조회 (읽기 전용)
6. **활동중인 동아리** — 합격한 동아리 목록 조회

### MVP API 목록

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/v1/auth/email-verify/send` | 청주대 이메일로 인증번호 발송 |
| POST | `/api/v1/auth/email-verify/confirm` | 인증번호 확인 |
| POST | `/api/v1/auth/register` | 회원가입 (개인정보 동의 포함) |
| POST | `/api/v1/auth/login` | 로그인 → JWT 반환 |
| GET | `/api/v1/clubs/{club_id}` | 동아리 상세 조회 |
| GET | `/api/v1/clubs/{club_id}/form` | 해당 동아리 신청 폼(질문 목록) 조회 |
| POST | `/api/v1/applications` | 신청서 임시저장 또는 제출 (is_draft로 구분) |
| PATCH | `/api/v1/applications/{id}` | 임시저장 신청서 수정 또는 제출 |
| GET | `/api/v1/me/applications/drafts` | 임시저장함 목록 조회 |
| GET | `/api/v1/me/applications/drafts/{id}` | 임시저장 신청서 상세 조회 |
| GET | `/api/v1/me/applications/submitted` | 제출한 신청서 목록 (상태 포함) |
| GET | `/api/v1/me/applications/submitted/{id}` | 제출한 신청서 상세 조회 (읽기 전용) |
| GET | `/api/v1/me/clubs` | 활동중인(합격한) 동아리 목록 조회 |

---

## 추후 개발 예정 (MVP 이후)

- 동아리 목록 조회 및 검색 (비회원 포함)
- 동아리 등록 및 상세페이지 관리 (관리자)
- 동아리 게시판 CRUD (부원/관리자)
- 동아리 신청 폼 커스텀 (관리자)
- 신청서 심사 (관리자)
- 동아리 회원 관리 및 권한 이전 (관리자)
- 알림 시스템 (인앱 알림 우선, 이메일/문자 추후 결정)
- 동아리 탈퇴 신청 프로세스
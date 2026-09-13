# Dream Lounge Backend API

> 청주대학교 동아리 관리 시스템 웹 플랫폼 - 백엔드 서버

## 📋 프로젝트 개요

Dream Lounge는 청주대학교 학생들이 동아리에 가입하고, 활동을 관리할 수 있는 통합 플랫폼입니다.

**주요 기능:**
- 🔐 간편 회원가입/로그인 (10자리 학번 + 8자리 이상·특수문자 포함 비밀번호)
- 🏢 동아리 검색 및 상세정보 조회
- 📝 동아리 신청서 작성 및 제출
- 📌 동아리 게시판 및 커뮤니티
- 👨‍💼 동아리 관리자 기능
- 🔔 인앱 알림

## 🛠 기술 스택

| 항목 | 기술 |
|------|------|
| **프레임워크** | FastAPI |
| **데이터베이스** | PostgreSQL (Supabase) |
| **ORM** | SQLAlchemy |
| **인증** | JWT (python-jose) |
| **이메일** | Resend |
| **패키지 관리** | UV |
| **파이썬** | 3.10+ |

## 🚀 빠른 시작

### 필수 요구사항
- Python 3.10 이상
- UV 패키지 관리자
- Supabase 계정 및 API 키

### 설치 방법

1. **저장소 클론**
```bash
cd /Users/jw/project/Develop/DreamLounge/dreamlounge_be
```

2. **가상 환경 생성 및 활성화**
```bash
uv venv
source .venv/bin/activate
```

3. **의존성 설치**
```bash
uv sync
```

4. **환경 변수 설정**
```bash
cp .env.example .env
# .env 파일을 편집하여 필요한 설정값 입력
```

5. **데이터베이스**

간소화 버전 전용 Supabase 프로젝트를 사용합니다. 관리자 연결은
`MIGRATION_DATABASE_URL`, 운영 API의 제한 계정 연결은 `DATABASE_URL`에 넣고
다음 명령으로 스키마를 적용합니다.

```bash
uv run alembic upgrade head
uv run python scripts/verify_production_db.py
```

DigitalOcean 컨테이너 2개에서 컨테이너별 `DB_POOL_SIZE=12`,
`DB_MAX_OVERFLOW=8`을 사용할 경우 최대 백엔드 연결은 40개입니다.
마이그레이션 `0021`은 `dreamlounge_backend` 역할 제한을 50개로 조정합니다.
마이그레이션 `0022`는 브라우저 기기별 인증 요청 제한용 해시 컬럼과
관리자 한 명당 하나의 활성 회장 동아리만 허용하는 DB 제약을 추가합니다.
배포 후 SQL Editor에서 다음 쿼리 결과가 `50`인지 확인합니다.

```sql
SELECT rolname, rolconnlimit
FROM pg_roles
WHERE rolname = 'dreamlounge_backend';
```

기존 프로젝트에서 회원을 제외한 동아리 카탈로그만 옮길 때는 먼저 dry run을
실행한 후 `--apply`를 사용합니다.

```bash
uv run python scripts/migrate_club_catalog.py \
  --source-env ../dreamlounge_be/.env \
  --target-env .env \
  --expected-target-ref <project-ref>
```

6. **개발 서버 실행**
```bash
uv run uvicorn src.main:app --reload
```

서버는 `http://localhost:8000`에서 실행됩니다.
- API 문서: http://localhost:8000/docs (Swagger UI)
- ReDoc: http://localhost:8000/redoc

## 📁 프로젝트 구조

```
dreamlounge_be/
├── src/
│   ├── main.py                  # FastAPI 앱 진입점
│   ├── config.py                # 환경설정
│   ├── database.py              # DB 설정
│   ├── models/                  # SQLAlchemy ORM 모델
│   │   ├── user.py
│   │   ├── club.py
│   │   ├── application.py
│   │   ├── post.py
│   │   ├── comment.py
│   │   └── email_verification.py
│   ├── schemas/                 # Pydantic 요청/응답 스키마
│   ├── crud/                    # 데이터베이스 쿼리 함수
│   ├── api/v1/                  # API 라우트
│   │   ├── auth.py
│   │   ├── users.py
│   │   ├── clubs.py
│   │   ├── applications.py
│   │   ├── posts.py
│   │   └── comments.py
│   ├── services/                # 비즈니스 로직
│   │   ├── auth_service.py
│   │   ├── email_service.py
│   │   ├── user_service.py
│   │   ├── club_service.py
│   │   ├── application_service.py
│   │   ├── post_service.py
│   │   └── comment_service.py
│   └── utils/                   # 유틸리티 함수
│       ├── security.py
│       ├── validators.py
│       └── constants.py
├── alembic/                     # 데이터베이스 마이그레이션
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── tests/                       # 테스트 스위트
│   ├── conftest.py
│   └── test_*.py
├── docs/                        # 문서
│   ├── API.md
│   └── DATABASE.md
├── pyproject.toml               # 프로젝트 설정
├── alembic.ini                  # Alembic 설정
├── .env.example                 # 환경변수 예시
├── .python-version              # Python 버전
└── README.md
```

## 📚 API 문서

상세한 API 엔드포인트 문서는 [docs/API.md](docs/API.md)를 참고하세요.

주요 엔드포인트:
- **인증**: `/api/v1/auth/*`
- **사용자**: `/api/v1/users/*`
- **동아리**: `/api/v1/clubs/*`
- **신청서**: `/api/v1/applications/*`
- **게시글**: `/api/v1/posts/*`
- **댓글**: `/api/v1/comments/*`

## 🗄 데이터베이스

데이터베이스 스키마 정보는 [docs/DATABASE.md](docs/DATABASE.md)를 참고하세요.

## 🧪 테스트

```bash
# 모든 테스트 실행
pytest

# 특정 파일 테스트
pytest tests/test_auth.py

# 커버리지 리포트
pytest --cov=src tests/
```

## 📝 코드 스타일

```bash
# Black으로 코드 포맷팅
black src tests

# Ruff로 린팅
ruff check src tests
```

## 🔄 데이터베이스 마이그레이션

```bash
# 새 마이그레이션 생성 (자동 감지)
alembic revision --autogenerate -m "마이그레이션 설명"

# 마이그레이션 적용
alembic upgrade head

# 마이그레이션 되돌리기
alembic downgrade -1

# 마이그레이션 히스토리
alembic history
```

## 🔒 보안

- JWT 토큰 기반 인증
- 비밀번호는 bcrypt로 해싱
- CORS 설정으로 허용된 도메인만 접근
- 학번별·IP별 로그인/가입 시도 제한과 계정 잠금
- 회전형 refresh token의 해시 저장 및 재사용 차단
- 동아리별 회장 권한을 백엔드에서 매 요청마다 검증
- 브라우저의 Supabase Data API 직접 접근 차단 및 전체 public 테이블 RLS 적용

## ⚠️ 비밀번호 인증

신규 회원가입 비밀번호는 8자리 이상이며 특수문자를 1개 이상 포함해야 합니다.
기존 4자리 비밀번호 계정은 비밀번호 변경 기능이 제공되기 전까지 로그인 호환성을 유지합니다.

## 🐛 트러블슈팅

### 데이터베이스 연결 오류
- `.env` 파일의 `DATABASE_URL`이 올바른지 확인
- Supabase 프로젝트가 실행 중인지 확인

### 이메일 발송 실패
- Resend API 키가 올바른지 확인
- 발신 이메일 주소가 Resend에서 검증되었는지 확인

## 📞 지원

문제가 있거나 기능을 제안하려면 이슈를 등록해주세요.

## 📄 라이선스

Proprietary License - 무단 복제, 배포 금지

---

**마지막 업데이트**: 2026년 5월 12일

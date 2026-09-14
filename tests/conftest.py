import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# 테스트가 개발/운영 .env의 Supabase Auth 사용자를 생성하거나 삭제하지 않도록
# 애플리케이션 설정이 로드되기 전에 외부 Auth 연동을 비활성화한다.
os.environ["SUPABASE_SERVICE_KEY"] = ""
from src.main import app
from src.db.base import Base
from src.db.session import get_db

TEST_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session", autouse=True)
def setup_db():
    import src.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clean_db():
    """각 테스트 후 모든 테이블 초기화."""
    yield
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.execute(text("PRAGMA foreign_keys = ON"))


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────────

def register_and_login(client, db, student_id: str, password: str = "test1234!") -> str:
    """간편 회원가입 후 로그인하고 access_token을 반환한다."""
    register = client.post(
        "/api/v1/auth/register",
        json={"student_id": student_id, "name": "테스트사용자", "password": password},
    )
    assert register.status_code == 201

    client.post("/api/v1/auth/login", json={"student_id": student_id, "password": password})
    token = client.cookies.get("dreamlounge_access")
    assert token
    return token


@pytest.fixture
def user_token(client, db) -> str:
    return register_and_login(client, db, "2021000001")


@pytest.fixture
def auth_headers(user_token) -> dict:
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture
def designated_admin_headers(db, auth_headers) -> dict:
    """일반 테스트 사용자를 운영자 지정 관리자 목록에 등록한다."""
    from src.models.club_admin import ClubAdmin
    from src.models.user import User

    user = db.query(User).filter(User.student_id == "2021000001").one()
    db.add(ClubAdmin(user_id=user.id, note="테스트 지정 관리자"))
    db.commit()
    return auth_headers


@pytest.fixture
def president_token(client, seeded_club) -> str:
    client.post("/api/v1/auth/login", json={"student_id": "PRES0000001", "password": "Password1!"})
    token = client.cookies.get("dreamlounge_access")
    assert token
    return token


@pytest.fixture
def president_headers(president_token) -> dict:
    return {"Authorization": f"Bearer {president_token}"}


@pytest.fixture
def seeded_club(db) -> dict:
    """테스트용 동아리 + 활성 신청 폼 + 질문 1개를 DB에 직접 생성."""
    from src.models.user import User
    from src.models.club import Club
    from src.models.club_member import ClubMember
    from src.models.club_admin import ClubAdmin
    from src.models.application import ApplicationForm, FormQuestion
    from src.core.security import hash_password

    president = User(
        student_id="PRES0000001",
        password_hash=hash_password("Password1!"),
        name="동아리회장",
        email="president@cju.ac.kr",
        email_verified=True,
    )
    db.add(president)
    db.flush()

    club = Club(
        president_id=president.id,
        name="테스트동아리",
        club_type="central",
        description="테스트용 동아리입니다.",
        is_recruiting=True,
    )
    db.add(club)
    db.flush()

    db.add(ClubMember(club_id=club.id, user_id=president.id, role="president", status="active"))
    db.add(ClubAdmin(user_id=president.id, note="테스트 동아리 회장"))

    form = ApplicationForm(club_id=club.id, title="2025년 신입부원 모집")
    db.add(form)
    db.flush()

    question = FormQuestion(
        form_id=form.id,
        question_text="지원 동기를 작성해주세요.",
        question_type="text",
        is_required=True,
        order_index=0,
    )
    db.add(question)
    db.commit()

    db.refresh(club)
    db.refresh(form)
    db.refresh(question)

    return {"club": club, "form": form, "question": question, "president": president}

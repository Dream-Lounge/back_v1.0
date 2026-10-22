from src.core.security import create_access_token, hash_password
from src.models.application import Application
from src.models.club_member import ClubMember
from src.models.post import Post
from src.models.user import AuditLog, AuthSession, PlatformRole, User
from tests.conftest import register_and_login


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': user.id})}"}


def _member_application_payload(seeded_club: dict, *, draft: bool = False) -> dict:
    return {
        "form_id": seeded_club["form"].id,
        "is_draft": draft,
        "privacy_consent": not draft,
        "applicant_department": "컴퓨터공학과",
        "applicant_phone": "010-1234-5678",
        "applicant_grade": "2",
        "answers": [
            {
                "question_id": seeded_club["question"].id,
                "answer_text": "지원 동기입니다.",
            }
        ],
    }


def _guest_application_payload(seeded_club: dict) -> dict:
    return {
        "form_id": seeded_club["form"].id,
        "applicant_student_id": "2026999999",
        "applicant_name": "비회원지원자",
        "applicant_department": "컴퓨터공학과",
        "applicant_phone": "010-9999-9999",
        "applicant_email": "guest@example.com",
        "applicant_grade": "2",
        "privacy_consent": True,
        "guest_notice_consent": True,
        "privacy_policy_version": "test-v1",
        "answers": [
            {
                "question_id": seeded_club["question"].id,
                "answer_text": "비회원 지원 동기입니다.",
            }
        ],
    }


def test_password_change_revokes_local_sessions_and_guide_is_recorded(client, db):
    token = register_and_login(client, db, "2026333001")
    headers = {"Authorization": f"Bearer {token}"}
    user = db.query(User).filter(User.student_id == "2026333001").one()
    assert db.query(AuthSession).filter(AuthSession.user_id == user.id).count() == 1

    guide = client.post("/api/v1/auth/me/guide-seen", headers=headers)
    changed = client.post(
        "/api/v1/auth/password/change",
        headers=headers,
        json={"current_password": "test1234!", "new_password": "new-password!"},
    )

    assert guide.status_code == 200
    assert guide.json()["guide_seen"] is True
    assert changed.status_code == 204
    assert db.query(AuthSession).filter(AuthSession.user_id == user.id).count() == 0
    assert client.post(
        "/api/v1/auth/login",
        json={"student_id": user.student_id, "password": "test1234!"},
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/login",
        json={"student_id": user.student_id, "password": "new-password!"},
    ).status_code == 200


def test_submitted_application_requires_manager_soft_delete(client, db, auth_headers, seeded_club):
    created = client.post(
        "/api/v1/applications",
        headers=auth_headers,
        json=_member_application_payload(seeded_club),
    )
    assert created.status_code == 201, created.text
    application_id = created.json()["id"]

    user_delete = client.delete(
        f"/api/v1/applications/{application_id}", headers=auth_headers
    )
    manager_delete = client.request(
        "DELETE",
        f"/api/v1/clubs/{seeded_club['club'].id}/applications/{application_id}",
        headers=_headers(seeded_club["president"]),
        json={"reason": "지원자 요청"},
    )
    hidden_from_user = client.get(
        f"/api/v1/me/applications/submitted/{application_id}", headers=auth_headers
    )

    assert user_delete.status_code == 400
    assert manager_delete.status_code == 204
    assert hidden_from_user.status_code == 404
    application = db.get(Application, application_id)
    assert application.deleted_at is not None
    assert application.deleted_by == seeded_club["president"].id
    assert application.deletion_reason == "지원자 요청"
    assert db.query(AuditLog).filter(
        AuditLog.action == "application.soft_deleted",
        AuditLog.target_id == application_id,
    ).count() == 1


def test_guest_application_acceptance_linking_and_csv(client, db, seeded_club):
    rejected_payload = _guest_application_payload(seeded_club)
    rejected_payload["guest_notice_consent"] = False
    rejected = client.post("/api/v1/guest/applications", json=rejected_payload)
    assert rejected.status_code == 422

    guest = client.post(
        "/api/v1/guest/applications", json=_guest_application_payload(seeded_club)
    )
    assert guest.status_code == 201, guest.text
    application_id = guest.json()["id"]
    assert guest.json()["applicant_type"] == "guest"
    assert db.get(Application, application_id).guest_notice_agreed_at is not None

    president_headers = _headers(seeded_club["president"])
    comment = client.patch(
        f"/api/v1/clubs/{seeded_club['club'].id}/applications/{application_id}/comment",
        headers=president_headers,
        json={"comment": "작성할 수 없어야 합니다."},
    )
    accepted = client.patch(
        f"/api/v1/clubs/{seeded_club['club'].id}/applications/{application_id}/status",
        headers=president_headers,
        json={"status": "passed"},
    )
    exported = client.get(
        f"/api/v1/clubs/{seeded_club['club'].id}/applications/export.csv",
        headers=president_headers,
        params={"applicant_type": "guest"},
    )

    assert comment.status_code == 400
    assert accepted.status_code == 200
    accepted_row = db.get(Application, application_id)
    assert accepted_row.accepted_at is not None
    assert accepted_row.link_expires_at is not None
    assert db.query(ClubMember).filter(
        ClubMember.club_id == seeded_club["club"].id,
        ClubMember.user_id.is_(None),
    ).count() == 0
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "비회원지원자" in exported.content.decode("utf-8-sig")

    linked_user = User(
        student_id="2026999999",
        password_hash=hash_password("password!"),
        name="비회원지원자",
        phone="010-9999-9999",
        department="컴퓨터공학과",
        email="guest@example.com",
        email_verified=True,
    )
    db.add(linked_user)
    db.commit()
    linked = client.post(
        "/api/v1/me/applications/link-guest", headers=_headers(linked_user)
    )

    assert linked.status_code == 200, linked.text
    assert linked.json()["linked_application_ids"] == [application_id]
    assert db.query(ClubMember).filter(
        ClubMember.club_id == seeded_club["club"].id,
        ClubMember.user_id == linked_user.id,
        ClubMember.status == "active",
    ).count() == 1
    assert db.get(Application, application_id).linked_user_id == linked_user.id


def test_platform_roles_service_board_and_anonymous_global_post(client, db):
    author = User(
        student_id="2026333002",
        password_hash=hash_password("password!"),
        name="운영자",
        phone="010-3333-3333",
        department="컴퓨터공학과",
        email="operator@example.com",
        email_verified=True,
    )
    db.add(author)
    db.flush()
    db.add(PlatformRole(user_id=author.id, role="developer"))
    db.commit()
    headers = _headers(author)

    service = client.post(
        "/api/v1/boards/service/posts",
        headers=headers,
        json={"title": "서비스 공지", "content": "점검 안내"},
    )
    anonymous = client.post(
        "/api/v1/boards/global/posts",
        headers=headers,
        json={"title": "익명 글", "content": "내용", "is_anonymous": True},
    )
    public_service = client.get("/api/v1/boards/service/posts")

    assert service.status_code == 201, service.text
    assert public_service.status_code == 200
    assert public_service.json()["total"] == 1
    assert anonymous.status_code == 201
    assert anonymous.json()["author_id"] is None
    assert anonymous.json()["author_name"] == "익명"
    stored = db.query(Post).filter(Post.title == "익명 글").one()
    assert stored.author_id == author.id
    assert stored.is_anonymous is True


def test_manager_cannot_withdraw_president_or_another_admin(client, db, seeded_club):
    club = seeded_club["club"]
    admin = User(
        student_id="2026333003",
        password_hash=hash_password("password!"),
        name="동아리관리자",
        phone="010-4444-4444",
        department="컴퓨터공학과",
        email="club-admin@example.com",
        email_verified=True,
    )
    other_admin = User(
        student_id="2026333004",
        password_hash=hash_password("password!"),
        name="다른관리자",
        phone="010-5555-5555",
        department="컴퓨터공학과",
        email="other-admin@example.com",
        email_verified=True,
    )
    db.add_all([admin, other_admin])
    db.flush()
    db.add_all([
        ClubMember(club_id=club.id, user_id=admin.id, role="admin", status="active"),
        ClubMember(club_id=club.id, user_id=other_admin.id, role="admin", status="active"),
    ])
    db.commit()
    headers = _headers(admin)

    president_result = client.patch(
        f"/api/v1/clubs/{club.id}/members/{seeded_club['president'].id}/withdraw",
        headers=headers,
    )
    admin_result = client.patch(
        f"/api/v1/clubs/{club.id}/members/{other_admin.id}/withdraw",
        headers=headers,
    )

    assert president_result.status_code == 400
    assert admin_result.status_code == 400

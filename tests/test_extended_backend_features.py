from unittest.mock import MagicMock, patch

import pytest

from src.core.config import settings
from src.core.security import create_access_token, hash_password, verify_password
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
    guide_hidden = client.post("/api/v1/auth/me/guide-hide-today", headers=headers)
    changed = client.post(
        "/api/v1/auth/password/change",
        headers=headers,
        json={"current_password": "test1234!", "new_password": "new-password!"},
    )

    assert guide.status_code == 200
    assert guide.json()["guide_seen"] is True
    assert guide_hidden.status_code == 200
    assert guide_hidden.json()["guide_hidden_until"] is not None
    assert changed.status_code == 204
    assert db.query(AuthSession).filter(AuthSession.user_id == user.id).count() == 0
    assert user.password_changed_at is not None
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert client.post(
        "/api/v1/auth/login",
        json={"student_id": user.student_id, "password": "test1234!"},
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/login",
        json={"student_id": user.student_id, "password": "new-password!"},
    ).status_code == 200


def test_password_change_does_not_sign_out_already_invalidated_supabase_session(client, db):
    token = register_and_login(client, db, "2026333002")
    user = db.query(User).filter(User.student_id == "2026333002").one()
    user.auth_user_id = "00000000-0000-0000-0000-000000000002"
    db.commit()
    admin_client = MagicMock()

    with (
        patch.object(settings, "SUPABASE_SERVICE_KEY", "test-service-key"),
        patch(
            "src.services.auth_service.get_supabase_admin_client",
            return_value=admin_client,
        ),
    ):
        changed = client.post(
            "/api/v1/auth/password/change",
            headers={"Authorization": f"Bearer {token}"},
            json={"current_password": "test1234!", "new_password": "new-password!"},
        )

    assert changed.status_code == 204
    admin_client.auth.admin.update_user_by_id.assert_called_once()
    admin_client.auth.admin.sign_out.assert_not_called()
    assert verify_password("new-password!", user.password_hash)


def test_password_change_restores_supabase_password_when_db_commit_fails(client, db):
    register_and_login(client, db, "2026333003")
    user = db.query(User).filter(User.student_id == "2026333003").one()
    user.auth_user_id = "00000000-0000-0000-0000-000000000003"
    db.commit()
    admin_client = MagicMock()

    with (
        patch.object(settings, "SUPABASE_SERVICE_KEY", "test-service-key"),
        patch(
            "src.services.auth_service.get_supabase_admin_client",
            return_value=admin_client,
        ),
        patch.object(db, "commit", side_effect=RuntimeError("forced commit failure")),
        pytest.raises(RuntimeError, match="비밀번호 변경을 완료하지 못했습니다"),
    ):
        from src.services import auth_service

        auth_service.change_password(
            db,
            user,
            "test1234!",
            "new-password!",
        )

    assert admin_client.auth.admin.update_user_by_id.call_count == 2
    first_password = admin_client.auth.admin.update_user_by_id.call_args_list[0].args[1][
        "password"
    ]
    restored_password = admin_client.auth.admin.update_user_by_id.call_args_list[1].args[1][
        "password"
    ]
    assert first_password != restored_password
    assert verify_password("test1234!", user.password_hash)


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
    assert accepted_row.applicant_email is None
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
    member_filter = client.get(
        f"/api/v1/clubs/{seeded_club['club'].id}/applications",
        headers=president_headers,
        params={"applicant_type": "member"},
    )
    guest_filter = client.get(
        f"/api/v1/clubs/{seeded_club['club'].id}/applications",
        headers=president_headers,
        params={"applicant_type": "guest"},
    )
    assert member_filter.status_code == 200
    assert [item["id"] for item in member_filter.json()["items"]] == [application_id]
    assert member_filter.json()["items"][0]["applicant_type"] == "member"
    assert guest_filter.status_code == 200
    assert guest_filter.json()["items"] == []
    linked_comment = client.patch(
        f"/api/v1/clubs/{seeded_club['club'].id}/applications/{application_id}/comment",
        headers=president_headers,
        json={"comment": "회원 연결 후 코멘트"},
    )
    assert linked_comment.status_code == 200
    assert linked_comment.json()["admin_comment"] == "회원 연결 후 코멘트"
    linked_history = client.get(
        "/api/v1/me/applications/submitted", headers=_headers(linked_user)
    )
    assert linked_history.status_code == 200
    assert [item["id"] for item in linked_history.json()] == [application_id]


def test_guest_application_can_link_before_review_and_membership_starts_after_pass(
    client, db, seeded_club
):
    payload = _guest_application_payload(seeded_club)
    payload.update({
        "applicant_student_id": "2026888888",
        "applicant_name": "심사전지원자",
        "applicant_phone": "010-8888-8888",
    })
    guest = client.post("/api/v1/guest/applications", json=payload)
    assert guest.status_code == 201, guest.text
    application_id = guest.json()["id"]

    linked_user = User(
        student_id="2026888888",
        password_hash=hash_password("password!"),
        name="심사전지원자",
        phone="01088888888",
        department="컴퓨터공학과",
        email="pending-guest@example.com",
        email_verified=True,
    )
    db.add(linked_user)
    db.commit()
    headers = _headers(linked_user)

    linked = client.post("/api/v1/me/applications/link-guest", headers=headers)
    history = client.get("/api/v1/me/applications/submitted", headers=headers)
    assert linked.status_code == 200, linked.text
    assert history.status_code == 200
    assert [item["id"] for item in history.json()] == [application_id]
    assert db.query(ClubMember).filter(
        ClubMember.club_id == seeded_club["club"].id,
        ClubMember.user_id == linked_user.id,
        ClubMember.status == "active",
    ).count() == 0

    passed = client.patch(
        f"/api/v1/clubs/{seeded_club['club'].id}/applications/{application_id}/status",
        headers=_headers(seeded_club["president"]),
        json={"status": "passed"},
    )
    assert passed.status_code == 200, passed.text
    assert db.query(ClubMember).filter(
        ClubMember.club_id == seeded_club["club"].id,
        ClubMember.user_id == linked_user.id,
        ClubMember.status == "active",
    ).count() == 1


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
    assert anonymous.json()["can_manage"] is True
    anonymous_detail = client.get(
        f"/api/v1/boards/global/posts/{anonymous.json()['id']}", headers=headers
    )
    assert anonymous_detail.status_code == 200
    assert anonymous_detail.json()["can_manage"] is True
    stored = db.query(Post).filter(Post.title == "익명 글").one()
    assert stored.author_id == author.id
    assert stored.is_anonymous is True

    client.cookies.clear()
    public_global = client.get("/api/v1/boards/global/posts")
    public_global_detail = client.get(
        f"/api/v1/boards/global/posts/{anonymous.json()['id']}"
    )
    assert public_global.status_code == 200
    assert public_global_detail.status_code == 200
    public_write = client.post(
        "/api/v1/boards/global/posts",
        json={"title": "비회원 글", "content": "작성 차단"},
    )
    assert public_write.status_code == 401


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

from src.core.security import create_access_token
from src.models.club import Club, ClubTag
from src.models.club_member import ClubMember
from src.models.notification import Notification
from src.models.user import AuditLog, User, UserInterest
from tests.conftest import register_and_login


def _registration_payload(**changes):
    payload = {
        "student_id": "2026123456",
        "name": "신규사용자",
        "email": "new-user@example.com",
        "phone": "010-1234-5678",
        "department": "컴퓨터공학과",
        "password": "password!",
        "privacy_consent": {
            "required_agreed": True,
            "optional_agreed": False,
            "policy_version": "test-v1",
        },
    }
    payload.update(changes)
    return payload


def test_registration_requires_student_email_phone_and_current_consent(client):
    wrong_domain = client.post(
        "/api/v1/auth/register",
        json=_registration_payload(email="student@other.ac.kr"),
    )
    missing_phone_payload = _registration_payload()
    missing_phone_payload.pop("phone")
    missing_phone = client.post("/api/v1/auth/register", json=missing_phone_payload)
    stale_policy = client.post(
        "/api/v1/auth/register",
        json=_registration_payload(
            privacy_consent={
                "required_agreed": True,
                "optional_agreed": False,
                "policy_version": "old",
            }
        ),
    )

    assert wrong_domain.status_code == 422
    assert missing_phone.status_code == 422
    assert stale_policy.status_code == 400


def test_profile_interests_and_audit_flow(client, db):
    token = register_and_login(client, db, "2026123456")
    headers = {"Authorization": f"Bearer {token}"}

    immutable = client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"student_id": "2026000000"},
    )
    updated = client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"phone": "010-9999-8888", "department": "AI소프트웨어학과"},
    )
    interests = client.put(
        "/api/v1/auth/me/interests",
        headers=headers,
        json={
            "interests": [
                {"tag_key": "field", "tag_value": "개발"},
                {"tag_key": "atmosphere", "tag_value": "친목"},
            ]
        },
    )
    me = client.get("/api/v1/auth/me", headers=headers)

    assert immutable.status_code == 422
    assert updated.status_code == 200
    assert updated.json()["student_id"] == "2026123456"
    assert updated.json()["phone"] == "010-9999-8888"
    assert interests.status_code == 200
    assert interests.json()["onboarding_completed"] is True
    assert me.json()["onboarding_completed"] is True
    user = db.query(User).filter(User.student_id == "2026123456").one()
    assert db.query(UserInterest).filter(UserInterest.user_id == user.id).count() == 2
    assert db.query(AuditLog).filter(AuditLog.actor_user_id == user.id).count() >= 3


def test_club_filters_sorting_and_pagination(client, db):
    closed = Club(name="가나다", is_recruiting=False, division="체육")
    open_second = Club(name="나무", is_recruiting=True, division="체육")
    open_first = Club(name="가람", is_recruiting=True, division="학술")
    db.add_all([closed, open_second, open_first])
    db.flush()
    db.add_all(
        [
            ClubTag(club_id=open_second.id, tag_key="atmosphere", tag_value="친목"),
            ClubTag(club_id=open_first.id, tag_key="field", tag_value="개발"),
        ]
    )
    db.commit()

    all_clubs = client.get("/api/v1/clubs")
    recruiting = client.get("/api/v1/clubs", params={"is_recruiting": "true"})
    tagged = client.get("/api/v1/clubs/page", params={"tag": "개발", "size": 1})

    assert [club["name"] for club in all_clubs.json()] == ["가람", "나무", "가나다"]
    assert [club["name"] for club in recruiting.json()] == ["가람", "나무"]
    assert tagged.status_code == 200
    assert tagged.json()["total"] == 1
    assert tagged.json()["items"][0]["name"] == "가람"


def test_admin_can_withdraw_ordinary_member(client, db, seeded_club):
    club = seeded_club["club"]
    admin = User(
        student_id="2026000001",
        password_hash="unused",
        name="관리자",
        phone="010-1111-1111",
        email="admin@example.com",
        email_verified=True,
    )
    member = User(
        student_id="2026000002",
        password_hash="unused",
        name="부원",
        phone="010-2222-2222",
        email="member@example.com",
        email_verified=True,
    )
    db.add_all([admin, member])
    db.flush()
    db.add_all(
        [
            ClubMember(club_id=club.id, user_id=admin.id, role="admin", status="active"),
            ClubMember(club_id=club.id, user_id=member.id, role="member", status="active"),
        ]
    )
    db.commit()

    admin_headers = {"Authorization": f"Bearer {create_access_token({'sub': admin.id})}"}
    response = client.patch(
        f"/api/v1/clubs/{club.id}/members/{member.id}/withdraw",
        headers=admin_headers,
    )

    assert response.status_code == 204


def test_notification_page_and_unread_count(client, db, auth_headers):
    user = db.query(User).filter(User.student_id == "2021000001").one()
    db.add_all(
        [
            Notification(recipient_id=user.id, noti_type="new_notice", message="첫 알림"),
            Notification(recipient_id=user.id, noti_type="new_notice", message="둘째 알림"),
        ]
    )
    db.commit()

    page = client.get(
        "/api/v1/me/notifications/page",
        params={"page": 1, "size": 1},
        headers=auth_headers,
    )
    unread = client.get("/api/v1/me/notifications/unread-count", headers=auth_headers)

    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert len(page.json()["items"]) == 1
    assert unread.json() == {"count": 2}

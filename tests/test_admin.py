"""관리자(동아리 회장) 기능 통합 테스트."""
import pytest
from tests.conftest import register_and_login


# ── 공통 셋업 픽스처 ──────────────────────────────────────────────────────────

@pytest.fixture
def setup(client, db, seeded_club, auth_headers, president_headers):
    """공통 테스트 데이터: 동아리, 회장 헤더, 일반 유저 헤더, 폼 정보."""
    return {
        "club_id": seeded_club["club"].id,
        "form_id": seeded_club["form"].id,
        "question_id": seeded_club["question"].id,
        "president": seeded_club["president"],
        "president_headers": president_headers,
        "user_headers": auth_headers,
    }


# ── 동아리 등록·수정 ──────────────────────────────────────────────────────────

class TestClubCreate:
    def test_create_success(self, client, db, designated_admin_headers):
        resp = client.post("/api/v1/clubs", headers=designated_admin_headers, json={
            "name": "새동아리",
            "club_type": "central",
            "description": "설명",
            "is_recruiting": True,
            "tags": [{"tag_key": "분야", "tag_value": "음악"}],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "새동아리"
        assert len(data["tags"]) == 1

    def test_create_duplicate_name(self, client, designated_admin_headers, seeded_club):
        resp = client.post("/api/v1/clubs", headers=designated_admin_headers, json={
            "name": seeded_club["club"].name,
        })
        assert resp.status_code == 400

    def test_create_requires_auth(self, client):
        resp = client.post("/api/v1/clubs", json={"name": "비회원동아리"})
        assert resp.status_code in (401, 403)

    def test_regular_user_cannot_create_club(self, client, auth_headers):
        resp = client.post(
            "/api/v1/clubs", headers=auth_headers, json={"name": "권한없는동아리"}
        )
        assert resp.status_code == 403
        assert "지정된 동아리 관리자" in resp.json()["detail"]

    def test_creator_becomes_president(self, client, db, designated_admin_headers):
        from src.models.user import User
        from src.models.club_member import ClubMember

        resp = client.post("/api/v1/clubs", headers=designated_admin_headers, json={"name": "내동아리"})
        club_id = resp.json()["id"]

        user = db.query(User).filter(User.student_id == "2021000001").first()
        membership = db.query(ClubMember).filter(
            ClubMember.club_id == club_id,
            ClubMember.user_id == user.id,
            ClubMember.role == "president",
        ).first()
        assert membership is not None

    def test_designated_admin_cannot_create_more_than_one_club(
        self, client, designated_admin_headers
    ):
        first = client.post(
            "/api/v1/clubs",
            headers=designated_admin_headers,
            json={"name": "첫번째동아리"},
        )
        second = client.post(
            "/api/v1/clubs",
            headers=designated_admin_headers,
            json={"name": "두번째동아리"},
        )
        assert first.status_code == 201
        assert second.status_code == 400
        assert second.json()["detail"] == "관리자 한 명은 하나의 동아리만 개설할 수 있습니다."


class TestClubUpdate:
    def test_update_success(self, client, setup):
        resp = client.patch(f"/api/v1/clubs/{setup['club_id']}", headers=setup["president_headers"], json={
            "description": "수정된 설명",
            "is_recruiting": False,
        })
        assert resp.status_code == 200
        assert resp.json()["description"] == "수정된 설명"

    def test_update_tags(self, client, setup):
        resp = client.patch(f"/api/v1/clubs/{setup['club_id']}", headers=setup["president_headers"], json={
            "tags": [{"tag_key": "분위기", "tag_value": "활발"}],
        })
        assert resp.status_code == 200
        assert resp.json()["tags"][0]["tag_value"] == "활발"

    def test_update_requires_president(self, client, setup):
        resp = client.patch(f"/api/v1/clubs/{setup['club_id']}", headers=setup["user_headers"], json={
            "description": "해킹 시도",
        })
        assert resp.status_code == 403

    def test_president_cannot_update_another_club(self, client, db, setup):
        from src.models.club_admin import ClubAdmin
        from src.models.user import User

        other_token = register_and_login(client, db, "2021999998")
        other_headers = {"Authorization": f"Bearer {other_token}"}
        other_user = db.query(User).filter(User.student_id == "2021999998").one()
        db.add(ClubAdmin(user_id=other_user.id, note="다른 테스트 관리자"))
        db.commit()
        own_club = client.post(
            "/api/v1/clubs",
            headers=other_headers,
            json={"name": "다른관리자동아리"},
        )
        assert own_club.status_code == 201

        resp = client.patch(
            f"/api/v1/clubs/{setup['club_id']}",
            headers=other_headers,
            json={"description": "다른 동아리 수정 시도"},
        )
        assert resp.status_code == 403

    def test_update_accepts_long_contact_url(self, client, setup):
        long_url = "https://www.google.com/search?q=" + ("dreamlounge%20" * 40)
        assert len(long_url) > 255

        resp = client.patch(
            f"/api/v1/clubs/{setup['club_id']}",
            headers=setup["president_headers"],
            json={
                "contact_links": [
                    {"type": "url", "label": "오픈채팅", "value": long_url}
                ]
            },
        )

        assert resp.status_code == 200
        assert resp.json()["contact_links"][0]["value"] == long_url
        assert resp.json()["open_chat_url"] == long_url


# ── 신청 폼 관리 ──────────────────────────────────────────────────────────────

class TestFormManagement:
    def test_create_form(self, client, db, seeded_club, president_headers):
        """기존 폼을 비활성화하고 새 폼 생성."""
        from src.models.application import ApplicationForm
        db.query(ApplicationForm).filter(
            ApplicationForm.club_id == seeded_club["club"].id
        ).update({"is_active": False})
        db.commit()

        resp = client.post(
            f"/api/v1/clubs/{seeded_club['club'].id}/form",
            headers=president_headers,
            json={"title": "2025년 2학기 모집"},
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "2025년 2학기 모집"

    def test_create_form_duplicate_active(self, client, setup):
        """이미 활성 폼이 있으면 400."""
        resp = client.post(
            f"/api/v1/clubs/{setup['club_id']}/form",
            headers=setup["president_headers"],
            json={"title": "중복 폼"},
        )
        assert resp.status_code == 400

    def test_update_form(self, client, setup):
        resp = client.patch(
            f"/api/v1/clubs/{setup['club_id']}/form",
            headers=setup["president_headers"],
            json={"title": "수정된 폼 제목"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "수정된 폼 제목"

    def test_add_question(self, client, setup):
        resp = client.post(
            f"/api/v1/clubs/{setup['club_id']}/form/questions",
            headers=setup["president_headers"],
            json={
                "question_text": "자기소개를 해주세요.",
                "question_type": "text",
                "is_required": True,
                "order_index": 1,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["question_text"] == "자기소개를 해주세요."

    def test_update_question(self, client, setup):
        resp = client.patch(
            f"/api/v1/clubs/{setup['club_id']}/form/questions/{setup['question_id']}",
            headers=setup["president_headers"],
            json={"question_text": "수정된 질문"},
        )
        assert resp.status_code == 200
        assert resp.json()["question_text"] == "수정된 질문"

    def test_choice_question_update_requires_options(self, client, setup):
        resp = client.patch(
            f"/api/v1/clubs/{setup['club_id']}/form/questions/{setup['question_id']}",
            headers=setup["president_headers"],
            json={"question_type": "choice"},
        )
        assert resp.status_code == 400

    def test_delete_question(self, client, setup):
        resp = client.delete(
            f"/api/v1/clubs/{setup['club_id']}/form/questions/{setup['question_id']}",
            headers=setup["president_headers"],
        )
        assert resp.status_code == 204

    def test_reorder_questions(self, client, db, setup):
        from src.models.application import FormQuestion
        q2 = FormQuestion(
            form_id=setup["form_id"],
            question_text="두 번째 질문",
            question_type="text",
            is_required=False,
            order_index=1,
        )
        db.add(q2)
        db.commit()

        resp = client.post(
            f"/api/v1/clubs/{setup['club_id']}/form/questions/reorder",
            headers=setup["president_headers"],
            json={"question_ids": [q2.id, setup["question_id"]]},
        )
        assert resp.status_code == 200
        questions = resp.json()["questions"]
        assert questions[0]["id"] == q2.id
        assert questions[1]["id"] == setup["question_id"]

    def test_form_management_requires_president(self, client, setup):
        resp = client.post(
            f"/api/v1/clubs/{setup['club_id']}/form/questions",
            headers=setup["user_headers"],
            json={"question_text": "해킹 질문", "order_index": 0},
        )
        assert resp.status_code == 403


# ── 신청서 심사 ───────────────────────────────────────────────────────────────

class TestApplicationReview:
    @pytest.fixture
    def submitted_app(self, client, db, setup):
        """일반 유저가 신청서를 제출한 상태."""
        resp = client.post("/api/v1/applications", headers=setup["user_headers"], json={
            "form_id": setup["form_id"],
            "is_draft": False,
            "privacy_consent": True,
            "applicant_student_id": "2021000001",
            "applicant_name": "테스트유저",
            "applicant_department": "컴퓨터공학과",
            "applicant_phone": "01012345678",
            "applicant_grade": "2",
            "answers": [{"question_id": setup["question_id"], "answer_text": "지원합니다."}],
        })
        return resp.json()

    def test_list_applications(self, client, setup, submitted_app):
        resp = client.get(
            f"/api/v1/clubs/{setup['club_id']}/applications",
            headers=setup["president_headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["user_department"] == "컴퓨터공학과"

    def test_list_applications_filters_status(self, client, setup, submitted_app):
        submitted = client.get(
            f"/api/v1/clubs/{setup['club_id']}/applications?status=submitted",
            headers=setup["president_headers"],
        )
        assert submitted.status_code == 200
        assert submitted.json()["total"] == 1

        reviewed = client.patch(
            f"/api/v1/clubs/{setup['club_id']}/applications/{submitted_app['id']}/status",
            headers=setup["president_headers"],
            json={"status": "passed"},
        )
        assert reviewed.status_code == 200

        passed = client.get(
            f"/api/v1/clubs/{setup['club_id']}/applications?status=passed",
            headers=setup["president_headers"],
        )
        failed = client.get(
            f"/api/v1/clubs/{setup['club_id']}/applications?status=failed",
            headers=setup["president_headers"],
        )
        assert passed.status_code == 200
        assert passed.json()["total"] == 1
        assert failed.status_code == 200
        assert failed.json()["total"] == 0

    def test_get_application_detail(self, client, setup, submitted_app):
        resp = client.get(
            f"/api/v1/clubs/{setup['club_id']}/applications/{submitted_app['id']}",
            headers=setup["president_headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == submitted_app["id"]
        assert data["user_department"] == "컴퓨터공학과"
        assert len(data["answers"]) == 1
        assert data["answers"][0]["question_text"] == "지원 동기를 작성해주세요."
        assert data["answers"][0]["order_index"] == 0

    def test_export_applications_returns_questions_and_answers_in_batch(
        self, client, setup, submitted_app
    ):
        resp = client.get(
            f"/api/v1/clubs/{setup['club_id']}/applications/export?size=200",
            headers=setup["president_headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        answer = data["items"][0]["answers"][0]
        assert answer["question_text"] == "지원 동기를 작성해주세요."
        assert answer["answer_text"] == "지원합니다."

    def test_export_applications_applies_status_filter(
        self, client, setup, submitted_app
    ):
        client.patch(
            f"/api/v1/clubs/{setup['club_id']}/applications/{submitted_app['id']}/status",
            headers=setup["president_headers"],
            json={"status": "passed"},
        )
        passed = client.get(
            f"/api/v1/clubs/{setup['club_id']}/applications/export?status=passed",
            headers=setup["president_headers"],
        )
        failed = client.get(
            f"/api/v1/clubs/{setup['club_id']}/applications/export?status=failed",
            headers=setup["president_headers"],
        )
        assert passed.status_code == 200
        assert passed.json()["total"] == 1
        assert failed.status_code == 200
        assert failed.json()["total"] == 0

    def test_review_pending(self, client, setup, submitted_app):
        resp = client.patch(
            f"/api/v1/clubs/{setup['club_id']}/applications/{submitted_app['id']}/status",
            headers=setup["president_headers"],
            json={"status": "pending"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"
        assert resp.json()["user_department"] == "컴퓨터공학과"

    def test_review_passed_creates_member(self, client, db, setup, submitted_app):
        from src.models.user import User
        from src.models.club_member import ClubMember

        client.patch(
            f"/api/v1/clubs/{setup['club_id']}/applications/{submitted_app['id']}/status",
            headers=setup["president_headers"],
            json={"status": "passed"},
        )
        user = db.query(User).filter(User.student_id == "2021000001").first()
        member = db.query(ClubMember).filter(
            ClubMember.club_id == setup["club_id"],
            ClubMember.user_id == user.id,
            ClubMember.role == "member",
            ClubMember.status == "active",
        ).first()
        assert member is not None

    def test_review_failed(self, client, setup, submitted_app):
        resp = client.patch(
            f"/api/v1/clubs/{setup['club_id']}/applications/{submitted_app['id']}/status",
            headers=setup["president_headers"],
            json={"status": "failed"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"

    def test_cannot_review_twice(self, client, setup, submitted_app):
        client.patch(
            f"/api/v1/clubs/{setup['club_id']}/applications/{submitted_app['id']}/status",
            headers=setup["president_headers"],
            json={"status": "passed"},
        )
        resp = client.patch(
            f"/api/v1/clubs/{setup['club_id']}/applications/{submitted_app['id']}/status",
            headers=setup["president_headers"],
            json={"status": "failed"},
        )
        assert resp.status_code == 400

    def test_review_requires_president(self, client, setup, submitted_app):
        resp = client.patch(
            f"/api/v1/clubs/{setup['club_id']}/applications/{submitted_app['id']}/status",
            headers=setup["user_headers"],
            json={"status": "passed"},
        )
        assert resp.status_code == 403

    def test_review_sends_notification(self, client, db, setup, submitted_app):
        from src.models.notification import Notification
        from src.models.user import User

        client.patch(
            f"/api/v1/clubs/{setup['club_id']}/applications/{submitted_app['id']}/status",
            headers=setup["president_headers"],
            json={"status": "passed"},
        )
        user = db.query(User).filter(User.student_id == "2021000001").first()
        noti = db.query(Notification).filter(
            Notification.recipient_id == user.id,
            Notification.noti_type == "application_result",
        ).first()
        assert noti is not None

    def test_review_rolls_back_when_notification_cannot_be_queued(
        self, client, db, setup, submitted_app
    ):
        from unittest.mock import patch
        from src.models.application import Application

        with patch(
            "src.routers.v1.applications.notification_service.queue_application_result",
            side_effect=RuntimeError("notification failure"),
        ):
            with pytest.raises(RuntimeError, match="notification failure"):
                client.patch(
                    f"/api/v1/clubs/{setup['club_id']}/applications/{submitted_app['id']}/status",
                    headers=setup["president_headers"],
                    json={"status": "passed"},
                )

        db.rollback()
        db.expire_all()
        saved = db.get(Application, submitted_app["id"])
        assert saved.status == "submitted"

    def test_admin_comment_is_committed(self, client, db, setup, submitted_app):
        from src.models.application import Application

        response = client.patch(
            f"/api/v1/clubs/{setup['club_id']}/applications/{submitted_app['id']}/comment",
            headers=setup["president_headers"],
            json={"comment": "면접 시간을 확인해주세요."},
        )
        assert response.status_code == 200

        db.expire_all()
        saved = db.get(Application, submitted_app["id"])
        assert saved.admin_comment == "면접 시간을 확인해주세요."


# ── 게시판 CRUD ───────────────────────────────────────────────────────────────

class TestPostBoard:
    @pytest.fixture
    def member_setup(self, client, db, setup):
        """일반 유저를 부원으로 등록."""
        from src.models.user import User
        from src.models.club_member import ClubMember

        user = db.query(User).filter(User.student_id == "2021000001").first()
        db.add(ClubMember(
            club_id=setup["club_id"], user_id=user.id, role="member", status="active",
        ))
        db.commit()
        return setup

    def test_president_post_is_notice(self, client, setup):
        """회장이 작성하면 자동 공지."""
        resp = client.post(
            f"/api/v1/clubs/{setup['club_id']}/posts",
            headers=setup["president_headers"],
            json={"title": "공지", "content": "내용"},
        )
        assert resp.status_code == 201
        assert resp.json()["is_notice"] is True
        assert resp.json()["post_type"] == "notice"

    def test_member_post_is_general(self, client, member_setup):
        resp = client.post(
            f"/api/v1/clubs/{member_setup['club_id']}/posts",
            headers=member_setup["user_headers"],
            json={"title": "일반 글", "content": "내용"},
        )
        assert resp.status_code == 201
        assert resp.json()["is_notice"] is False
        assert resp.json()["post_type"] == "general"

    def test_list_posts(self, client, member_setup):
        client.post(
            f"/api/v1/clubs/{member_setup['club_id']}/posts",
            headers=member_setup["president_headers"],
            json={"title": "공지1", "content": "내용"},
        )
        client.post(
            f"/api/v1/clubs/{member_setup['club_id']}/posts",
            headers=member_setup["user_headers"],
            json={"title": "일반글", "content": "내용"},
        )
        resp = client.get(
            f"/api/v1/clubs/{member_setup['club_id']}/posts",
            headers=member_setup["user_headers"],
        )
        assert resp.status_code == 200
        posts = resp.json()
        assert posts[0]["is_notice"] is True

    def test_list_posts_requires_active_membership(self, client, setup):
        client.cookies.clear()
        unauthenticated = client.get(
            f"/api/v1/clubs/{setup['club_id']}/posts",
        )
        non_member = client.get(
            f"/api/v1/clubs/{setup['club_id']}/posts",
            headers=setup["user_headers"],
        )
        assert unauthenticated.status_code == 401
        assert non_member.status_code == 403

    def test_get_post_detail_with_comments(self, client, member_setup):
        post_resp = client.post(
            f"/api/v1/clubs/{member_setup['club_id']}/posts",
            headers=member_setup["president_headers"],
            json={"title": "공지", "content": "내용"},
        )
        post_id = post_resp.json()["id"]

        client.post(
            f"/api/v1/clubs/{member_setup['club_id']}/posts/{post_id}/comments",
            headers=member_setup["user_headers"],
            json={"content": "댓글입니다."},
        )

        resp = client.get(
            f"/api/v1/clubs/{member_setup['club_id']}/posts/{post_id}",
            headers=member_setup["user_headers"],
        )
        assert resp.status_code == 200
        assert len(resp.json()["comments"]) == 1

    def test_toggle_notice(self, client, member_setup):
        post_resp = client.post(
            f"/api/v1/clubs/{member_setup['club_id']}/posts",
            headers=member_setup["user_headers"],
            json={"title": "일반글", "content": "내용"},
        )
        post_id = post_resp.json()["id"]

        resp = client.patch(
            f"/api/v1/clubs/{member_setup['club_id']}/posts/{post_id}/notice",
            headers=member_setup["president_headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["is_notice"] is True

    def test_toggle_notice_requires_president(self, client, member_setup):
        post_resp = client.post(
            f"/api/v1/clubs/{member_setup['club_id']}/posts",
            headers=member_setup["president_headers"],
            json={"title": "공지", "content": "내용"},
        )
        post_id = post_resp.json()["id"]

        resp = client.patch(
            f"/api/v1/clubs/{member_setup['club_id']}/posts/{post_id}/notice",
            headers=member_setup["user_headers"],
        )
        assert resp.status_code == 403

    def test_delete_post_by_author(self, client, member_setup):
        post_resp = client.post(
            f"/api/v1/clubs/{member_setup['club_id']}/posts",
            headers=member_setup["user_headers"],
            json={"title": "내 글", "content": "내용"},
        )
        post_id = post_resp.json()["id"]

        resp = client.delete(
            f"/api/v1/clubs/{member_setup['club_id']}/posts/{post_id}",
            headers=member_setup["user_headers"],
        )
        assert resp.status_code == 204

    def test_president_can_delete_any_post(self, client, member_setup):
        post_resp = client.post(
            f"/api/v1/clubs/{member_setup['club_id']}/posts",
            headers=member_setup["user_headers"],
            json={"title": "부원 글", "content": "내용"},
        )
        post_id = post_resp.json()["id"]

        resp = client.delete(
            f"/api/v1/clubs/{member_setup['club_id']}/posts/{post_id}",
            headers=member_setup["president_headers"],
        )
        assert resp.status_code == 204

    def test_non_member_cannot_post(self, client, setup):
        resp = client.post(
            f"/api/v1/clubs/{setup['club_id']}/posts",
            headers=setup["user_headers"],
            json={"title": "비부원 글", "content": "내용"},
        )
        assert resp.status_code == 403

    def test_delete_comment_by_author(self, client, member_setup):
        post_resp = client.post(
            f"/api/v1/clubs/{member_setup['club_id']}/posts",
            headers=member_setup["president_headers"],
            json={"title": "공지", "content": "내용"},
        )
        post_id = post_resp.json()["id"]

        comment_resp = client.post(
            f"/api/v1/clubs/{member_setup['club_id']}/posts/{post_id}/comments",
            headers=member_setup["user_headers"],
            json={"content": "내 댓글"},
        )
        comment_id = comment_resp.json()["id"]

        resp = client.delete(
            f"/api/v1/clubs/{member_setup['club_id']}/posts/{post_id}/comments/{comment_id}",
            headers=member_setup["user_headers"],
        )
        assert resp.status_code == 204

    def test_notice_creates_notifications(self, client, db, member_setup):
        from src.models.notification import Notification

        client.post(
            f"/api/v1/clubs/{member_setup['club_id']}/posts",
            headers=member_setup["president_headers"],
            json={"title": "공지!", "content": "내용"},
        )
        notis = db.query(Notification).filter(
            Notification.noti_type == "new_notice",
        ).all()
        assert len(notis) >= 1


# ── 회원 관리 ─────────────────────────────────────────────────────────────────

class TestMemberManagement:
    @pytest.fixture
    def club_with_member(self, client, db, setup):
        """일반 유저를 부원으로 추가한 상태."""
        from src.models.user import User
        from src.models.club_member import ClubMember

        user = db.query(User).filter(User.student_id == "2021000001").first()
        db.add(ClubMember(
            club_id=setup["club_id"], user_id=user.id, role="member", status="active",
        ))
        db.commit()
        return {**setup, "member_user_id": user.id}

    def test_list_members(self, client, club_with_member):
        resp = client.get(
            f"/api/v1/clubs/{club_with_member['club_id']}/members",
            headers=club_with_member["president_headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2  # president + member
        roles = {m["role"] for m in data["items"]}
        assert "president" in roles
        assert "member" in roles

    def test_list_members_requires_president(self, client, club_with_member):
        resp = client.get(
            f"/api/v1/clubs/{club_with_member['club_id']}/members",
            headers=club_with_member["user_headers"],
        )
        assert resp.status_code == 403

    def test_withdraw_member(self, client, db, club_with_member):
        from src.models.club_member import ClubMember

        resp = client.patch(
            f"/api/v1/clubs/{club_with_member['club_id']}/members/{club_with_member['member_user_id']}/withdraw",
            headers=club_with_member["president_headers"],
        )
        assert resp.status_code == 204

        member = db.query(ClubMember).filter(
            ClubMember.club_id == club_with_member["club_id"],
            ClubMember.user_id == club_with_member["member_user_id"],
        ).first()
        assert member.status == "withdrawn"

    def test_cannot_withdraw_president(self, client, club_with_member):
        resp = client.patch(
            f"/api/v1/clubs/{club_with_member['club_id']}/members/{club_with_member['president'].id}/withdraw",
            headers=club_with_member["president_headers"],
        )
        assert resp.status_code == 400

    def test_transfer_role(self, client, db, club_with_member):
        from src.models.club_admin import ClubAdmin
        from src.models.club_member import ClubMember
        from src.models.club import Club

        db.add(ClubAdmin(user_id=club_with_member["member_user_id"], note="차기 회장"))
        db.commit()

        resp = client.patch(
            f"/api/v1/clubs/{club_with_member['club_id']}/members/{club_with_member['member_user_id']}/role",
            headers=club_with_member["president_headers"],
        )
        assert resp.status_code == 204

        new_president = db.query(ClubMember).filter(
            ClubMember.club_id == club_with_member["club_id"],
            ClubMember.user_id == club_with_member["member_user_id"],
        ).first()
        assert new_president.role == "president"

        old_president = db.query(ClubMember).filter(
            ClubMember.club_id == club_with_member["club_id"],
            ClubMember.user_id == club_with_member["president"].id,
        ).first()
        assert old_president.role == "member"

        club = db.get(Club, club_with_member["club_id"])
        assert club.president_id == club_with_member["member_user_id"]

    def test_cannot_transfer_role_to_undesignated_member(self, client, club_with_member):
        resp = client.patch(
            f"/api/v1/clubs/{club_with_member['club_id']}/members/{club_with_member['member_user_id']}/role",
            headers=club_with_member["president_headers"],
        )
        assert resp.status_code == 400
        assert "운영자가 지정한 관리자" in resp.json()["detail"]


# ── 알림 ──────────────────────────────────────────────────────────────────────

class TestNotifications:
    @pytest.fixture
    def with_notification(self, client, db, setup, auth_headers):
        """신청서 제출 + 심사 → 알림 생성 상태."""
        app_resp = client.post("/api/v1/applications", headers=auth_headers, json={
            "applicant_student_id": "2021000001",
            "applicant_name": "테스트유저",
            "applicant_department": "컴퓨터공학과",
            "applicant_phone": "01012345678",
            "applicant_grade": "2",
            "form_id": setup["form_id"],
            "is_draft": False,
            "privacy_consent": True,
            "answers": [{"question_id": setup["question_id"], "answer_text": "지원합니다."}],
        })
        client.patch(
            f"/api/v1/clubs/{setup['club_id']}/applications/{app_resp.json()['id']}/status",
            headers=setup["president_headers"],
            json={"status": "passed"},
        )
        return setup

    def test_list_notifications(self, client, auth_headers, with_notification):
        resp = client.get("/api/v1/me/notifications", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_mark_as_read(self, client, db, auth_headers, with_notification):
        from src.models.notification import Notification
        from src.models.user import User

        user = db.query(User).filter(User.student_id == "2021000001").first()
        noti = db.query(Notification).filter(Notification.recipient_id == user.id).first()

        resp = client.patch(f"/api/v1/me/notifications/{noti.id}/read", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["is_read"] is True

    def test_mark_all_as_read(self, client, auth_headers, with_notification):
        resp = client.patch("/api/v1/me/notifications/read-all", headers=auth_headers)
        assert resp.status_code == 204

    def test_notifications_require_auth(self, client):
        resp = client.get("/api/v1/me/notifications")
        assert resp.status_code in (401, 403)

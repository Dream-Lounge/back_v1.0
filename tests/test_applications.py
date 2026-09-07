import pytest
from tests.conftest import register_and_login


APPLICANT = {
    "applicant_student_id": "2021000001",
    "applicant_name": "테스트유저",
    "applicant_department": "컴퓨터공학과",
    "applicant_phone": "01012345678",
    "applicant_grade": "2",
}


@pytest.fixture
def app_setup(client, db, auth_headers, seeded_club):
    """인증된 일반 유저 + 동아리 폼 셋업."""
    return {
        "club_id": seeded_club["club"].id,
        "form_id": seeded_club["form"].id,
        "question_id": seeded_club["question"].id,
        "headers": auth_headers,
    }


# ── 신청서 생성 ────────────────────────────────────────────────────────────────

class TestCreateApplication:
    @pytest.mark.parametrize("is_draft", [True, False])
    def test_club_president_cannot_create_application(
        self, client, app_setup, president_headers, is_draft
    ):
        resp = client.post("/api/v1/applications", headers=president_headers, json={
            "form_id": app_setup["form_id"],
            "is_draft": is_draft,
            "answers": [{
                "question_id": app_setup["question_id"],
                "answer_text": "회장 신청 답변",
            }],
        })

        assert resp.status_code == 403
        assert resp.json()["detail"] == "동아리 관리자는 본인 동아리에 신청할 수 없습니다."

    def test_create_draft(self, client, app_setup):
        resp = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            "form_id": app_setup["form_id"],
            "is_draft": True,
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "임시저장 답변"}],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["is_draft"] is True
        assert data["status"] == "draft"
        assert data["submitted_at"] is None

    def test_create_submitted(self, client, app_setup):
        resp = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            **APPLICANT,
            "form_id": app_setup["form_id"],
            "is_draft": False,
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "제출 답변"}],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["is_draft"] is False
        assert data["status"] == "submitted"
        assert data["submitted_at"] is not None

    def test_cannot_submit_twice(self, client, app_setup):
        payload = {
            **APPLICANT,
            "form_id": app_setup["form_id"],
            "is_draft": False,
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "답변"}],
        }
        first = client.post("/api/v1/applications", headers=app_setup["headers"], json=payload)
        resp = client.post("/api/v1/applications", headers=app_setup["headers"], json=payload)
        assert first.status_code == 201
        assert resp.status_code == 400

    def test_submit_missing_required_answer(self, client, app_setup):
        """필수 질문 미답변 상태로 제출 시 400."""
        resp = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            "form_id": app_setup["form_id"],
            "is_draft": False,
            "answers": [],
        })
        assert resp.status_code == 400

    def test_submit_ignores_inactive_required_question(self, client, db, app_setup):
        """관리자가 삭제한 필수 문항은 최종 제출 검증에서 제외."""
        from src.models.application import FormQuestion

        question = db.get(FormQuestion, app_setup["question_id"])
        question.is_active = False
        db.commit()

        resp = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            **APPLICANT,
            "form_id": app_setup["form_id"],
            "is_draft": False,
            "answers": [],
        })
        assert resp.status_code == 201

    def test_draft_allows_missing_required_answer(self, client, app_setup):
        """임시저장은 필수 질문 미답변도 허용."""
        resp = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            "form_id": app_setup["form_id"],
            "is_draft": True,
            "answers": [],
        })
        assert resp.status_code == 201

    def test_draft_allows_blank_applicant_info(self, client, app_setup):
        """프론트가 빈 기본정보 문자열을 보내도 임시저장은 허용."""
        resp = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            "form_id": app_setup["form_id"],
            "is_draft": True,
            "answers": [],
            "applicant_name": "",
            "applicant_department": "",
            "applicant_phone": "",
            "applicant_grade": "",
        })
        assert resp.status_code == 201

    def test_create_requires_auth(self, client, app_setup):
        client.cookies.clear()
        resp = client.post("/api/v1/applications", json={
            "form_id": app_setup["form_id"],
            "is_draft": True,
            "answers": [],
        })
        assert resp.status_code in (401, 403)

    def test_invalid_form_id(self, client, app_setup):
        resp = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            "form_id": "nonexistent-form-id",
            "is_draft": True,
            "answers": [],
        })
        assert resp.status_code == 400

    def test_answers_are_saved(self, client, app_setup):
        resp = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            "form_id": app_setup["form_id"],
            "is_draft": True,
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "저장된 답변"}],
        })
        assert resp.status_code == 201
        answers = resp.json()["answers"]
        assert len(answers) == 1
        assert answers[0]["answer_text"] == "저장된 답변"


# ── 신청서 수정 ────────────────────────────────────────────────────────────────

class TestUpdateApplication:
    def _create_draft(self, client, app_setup, answer_text="초기 답변"):
        resp = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            "form_id": app_setup["form_id"],
            "is_draft": True,
            "answers": [{"question_id": app_setup["question_id"], "answer_text": answer_text}],
        })
        return resp.json()["id"]

    def test_update_answer(self, client, app_setup):
        app_id = self._create_draft(client, app_setup)
        resp = client.patch(f"/api/v1/applications/{app_id}", headers=app_setup["headers"], json={
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "수정된 답변"}],
        })
        assert resp.status_code == 200
        assert resp.json()["answers"][0]["answer_text"] == "수정된 답변"

    def test_update_draft_allows_blank_applicant_info(self, client, app_setup):
        app_id = self._create_draft(client, app_setup)
        resp = client.patch(f"/api/v1/applications/{app_id}", headers=app_setup["headers"], json={
            "is_draft": True,
            "answers": [],
            "applicant_name": "",
            "applicant_department": "",
            "applicant_phone": "",
            "applicant_grade": "",
        })
        assert resp.status_code == 200
        assert resp.json()["applicant_name"] is None

    def test_submit_from_draft(self, client, app_setup):
        app_id = self._create_draft(client, app_setup)
        resp = client.patch(f"/api/v1/applications/{app_id}", headers=app_setup["headers"], json={
            **APPLICANT,
            "is_draft": False,
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "최종 답변"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_draft"] is False
        assert data["status"] == "submitted"
        assert data["submitted_at"] is not None

    def test_cannot_update_submitted(self, client, app_setup):
        resp = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            **APPLICANT,
            "form_id": app_setup["form_id"],
            "is_draft": False,
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "답변"}],
        })
        app_id = resp.json()["id"]

        resp = client.patch(f"/api/v1/applications/{app_id}", headers=app_setup["headers"], json={
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "수정 시도"}],
        })
        assert resp.status_code == 400

    def test_not_found(self, client, auth_headers):
        resp = client.patch("/api/v1/applications/nonexistent-id", headers=auth_headers, json={
            "answers": [],
        })
        assert resp.status_code == 404

    def test_cannot_update_other_users_application(self, client, db, app_setup, seeded_club):
        """다른 유저의 신청서는 수정 불가."""
        app_id = self._create_draft(client, app_setup)

        other_token = register_and_login(client, db, "2021999999")
        other_headers = {"Authorization": f"Bearer {other_token}"}

        resp = client.patch(f"/api/v1/applications/{app_id}", headers=other_headers, json={
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "해킹 시도"}],
        })
        assert resp.status_code == 404

    @pytest.mark.parametrize("operation", ["update", "submit"])
    def test_cannot_change_draft_after_becoming_club_president(
        self, client, db, app_setup, seeded_club, operation
    ):
        """임시저장 후 회장이 되면 수정과 제출 모두 불가."""
        from src.models.club_member import ClubMember
        from src.models.user import User
        from src.services import member_service

        app_id = self._create_draft(client, app_setup)
        user = db.query(User).filter(User.student_id == "2021000001").first()
        db.add(ClubMember(
            club_id=app_setup["club_id"],
            user_id=user.id,
            role="member",
            status="active",
        ))
        db.commit()
        member_service.transfer_role(
            db,
            app_setup["club_id"],
            seeded_club["president"].id,
            user.id,
        )

        body = (
            {
                "answers": [{
                    "question_id": app_setup["question_id"],
                    "answer_text": "회장 취임 후 수정 시도",
                }],
            }
            if operation == "update"
            else {"is_draft": False}
        )
        resp = client.patch(
            f"/api/v1/applications/{app_id}",
            headers=app_setup["headers"],
            json=body,
        )

        assert resp.status_code == 403
        assert resp.json()["detail"] == "동아리 관리자는 본인 동아리에 신청할 수 없습니다."


# ── 임시저장함 ─────────────────────────────────────────────────────────────────

class TestDraftApplications:
    def test_empty_list(self, client, auth_headers):
        resp = client.get("/api/v1/me/applications/drafts", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_requires_auth(self, client):
        resp = client.get("/api/v1/me/applications/drafts")
        assert resp.status_code in (401, 403)

    def test_list_contains_drafts(self, client, app_setup):
        client.post("/api/v1/applications", headers=app_setup["headers"], json={
            "form_id": app_setup["form_id"],
            "is_draft": True,
            "answers": [],
        })
        resp = client.get("/api/v1/me/applications/drafts", headers=app_setup["headers"])
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_submitted_not_in_draft_list(self, client, app_setup):
        """제출된 신청서는 임시저장함에 나타나지 않아야 한다."""
        client.post("/api/v1/applications", headers=app_setup["headers"], json={
            "form_id": app_setup["form_id"],
            "is_draft": False,
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "답변"}],
        })
        resp = client.get("/api/v1/me/applications/drafts", headers=app_setup["headers"])
        assert resp.json() == []

    def test_draft_detail(self, client, app_setup):
        created = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            "form_id": app_setup["form_id"],
            "is_draft": True,
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "답변"}],
        }).json()

        resp = client.get(f"/api/v1/me/applications/drafts/{created['id']}", headers=app_setup["headers"])
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == created["id"]
        assert data["is_draft"] is True
        assert len(data["answers"]) == 1

    def test_draft_detail_not_found_for_submitted(self, client, app_setup):
        """제출된 신청서 id로 임시저장 상세 조회 시 404."""
        created = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            **APPLICANT,
            "form_id": app_setup["form_id"],
            "is_draft": False,
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "답변"}],
        }).json()

        resp = client.get(f"/api/v1/me/applications/drafts/{created['id']}", headers=app_setup["headers"])
        assert resp.status_code == 404


# ── 나의 신청서 ────────────────────────────────────────────────────────────────

class TestSubmittedApplications:
    def test_empty_list(self, client, auth_headers):
        resp = client.get("/api/v1/me/applications/submitted", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_requires_auth(self, client):
        resp = client.get("/api/v1/me/applications/submitted")
        assert resp.status_code in (401, 403)

    def test_list_contains_submitted(self, client, app_setup):
        client.post("/api/v1/applications", headers=app_setup["headers"], json={
            **APPLICANT,
            "form_id": app_setup["form_id"],
            "is_draft": False,
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "답변"}],
        })
        resp = client.get("/api/v1/me/applications/submitted", headers=app_setup["headers"])
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["status"] == "submitted"

    def test_draft_not_in_submitted_list(self, client, app_setup):
        client.post("/api/v1/applications", headers=app_setup["headers"], json={
            "form_id": app_setup["form_id"],
            "is_draft": True,
            "answers": [],
        })
        resp = client.get("/api/v1/me/applications/submitted", headers=app_setup["headers"])
        assert resp.json() == []

    def test_submitted_detail(self, client, app_setup):
        created = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            **APPLICANT,
            "form_id": app_setup["form_id"],
            "is_draft": False,
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "답변"}],
        }).json()

        resp = client.get(f"/api/v1/me/applications/submitted/{created['id']}", headers=app_setup["headers"])
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == created["id"]
        assert data["is_draft"] is False
        assert data["status"] == "submitted"

    def test_submitted_detail_keeps_original_question_after_form_edit(
        self, client, app_setup, president_headers
    ):
        created = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            **APPLICANT,
            "form_id": app_setup["form_id"],
            "is_draft": False,
            "answers": [{"question_id": app_setup["question_id"], "answer_text": "기존 답변"}],
        }).json()
        changed = client.patch(
            f"/api/v1/clubs/{app_setup['club_id']}/form/questions/{app_setup['question_id']}",
            headers=president_headers,
            json={"question_text": "변경된 질문"},
        )
        assert changed.status_code == 200

        detail = client.get(
            f"/api/v1/me/applications/submitted/{created['id']}",
            headers=app_setup["headers"],
        ).json()
        assert detail["answers"][0]["question_text"] != "변경된 질문"
        assert detail["answers"][0]["question_text"] == detail["form_snapshot"]["questions"][0]["question_text"]

    def test_submitted_detail_not_found_for_draft(self, client, app_setup):
        created = client.post("/api/v1/applications", headers=app_setup["headers"], json={
            "form_id": app_setup["form_id"],
            "is_draft": True,
            "answers": [],
        }).json()

        resp = client.get(f"/api/v1/me/applications/submitted/{created['id']}", headers=app_setup["headers"])
        assert resp.status_code == 404


# ── 활동중인 동아리 ────────────────────────────────────────────────────────────

class TestActiveClubs:
    def test_empty_when_no_membership(self, client, auth_headers):
        resp = client.get("/api/v1/me/clubs", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_requires_auth(self, client):
        resp = client.get("/api/v1/me/clubs")
        assert resp.status_code in (401, 403)

    def test_shows_approved_club(self, client, db, app_setup):
        """ClubMember에 직접 추가(합격 시뮬레이션) 후 목록에 나타나는지 확인."""
        from src.models.user import User
        from src.models.club_member import ClubMember

        user = db.query(User).filter(User.student_id == "2021000001").first()
        db.add(ClubMember(
            club_id=app_setup["club_id"],
            user_id=user.id,
            role="member",
            status="active",
        ))
        db.commit()

        resp = client.get("/api/v1/me/clubs", headers=app_setup["headers"])
        assert resp.status_code == 200
        clubs = resp.json()
        assert len(clubs) == 1
        assert clubs[0]["club_name"] == "테스트동아리"
        assert clubs[0]["role"] == "member"

    def test_withdrawn_member_not_shown(self, client, db, app_setup):
        """탈퇴 처리된 부원은 목록에 나타나지 않아야 한다."""
        from src.models.user import User
        from src.models.club_member import ClubMember

        user = db.query(User).filter(User.student_id == "2021000001").first()
        db.add(ClubMember(
            club_id=app_setup["club_id"],
            user_id=user.id,
            role="member",
            status="withdrawn",
        ))
        db.commit()

        resp = client.get("/api/v1/me/clubs", headers=app_setup["headers"])
        assert resp.json() == []

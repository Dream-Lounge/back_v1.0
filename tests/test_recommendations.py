from src.models.club import Club, ClubTag


def seed_recommendation_data(db, seeded_club):
    club = seeded_club["club"]
    club.name = "영상제작 동아리"
    club.description = (
        "매주 수요일 저녁에 모입니다. 영상 편집 경험이 없는 초보도 참여할 수 있으며 "
        "촬영을 배워 포트폴리오를 만듭니다."
    )
    club.is_recruiting = True
    db.add(ClubTag(club_id=club.id, tag_key="interest", tag_value="영상 편집"))
    db.commit()
    return club


def test_recommendation_returns_operational_club_id(client, db, seeded_club):
    club = seed_recommendation_data(db, seeded_club)

    response = client.post(
        "/api/v1/recommendations",
        json={"query": "초보인데 영상 편집을 배우고 포트폴리오를 만들고 싶어", "top_k": 3},
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["club_id"] == club.id
    assert response.json()["model_info"]["backend"] == "hashing"


def test_recommendation_qa_returns_grounded_evidence(client, db, seeded_club):
    club = seed_recommendation_data(db, seeded_club)

    response = client.post(
        "/api/v1/recommendations/qa",
        json={"question": "초보도 지원할 수 있어?", "club_id": club.id},
    )

    assert response.status_code == 200
    assert response.json()["supported"] is True
    assert "초보" in response.json()["answer"]
    assert response.json()["evidence"]
    assert response.json()["answer_source"] == "evidence"


def test_recommendation_qa_answers_generic_activity_question(client, db, seeded_club):
    club = seed_recommendation_data(db, seeded_club)

    response = client.post(
        "/api/v1/recommendations/qa",
        json={"question": "어떤 활동을 하나요?", "club_id": club.id},
    )

    assert response.status_code == 200
    assert response.json()["supported"] is True
    assert "영상 편집" in response.json()["answer"]


def test_recommendation_does_not_give_unrelated_clubs_a_neutral_score(client, db, seeded_club):
    seed_recommendation_data(db, seeded_club)
    db.add(
        Club(
            name="농구 동아리",
            description="매주 체육관에서 농구 경기를 합니다.",
            is_recruiting=True,
        )
    )
    db.commit()

    response = client.post(
        "/api/v1/recommendations",
        json={"query": "영상 편집", "top_k": 3},
    )

    results = response.json()["results"]
    assert results[0]["name"] == "영상제작 동아리"
    assert "농구 동아리" not in {result["name"] for result in results}


def test_recommendation_qa_abstains_without_evidence(client, seeded_club):
    response = client.post(
        "/api/v1/recommendations/qa",
        json={"question": "기숙사를 제공해?", "club_id": seeded_club["club"].id},
    )

    assert response.status_code == 200
    assert response.json()["supported"] is False


def test_recommendation_qa_returns_public_contact(client, db, seeded_club):
    club = seeded_club["club"]
    club.contact_email = "club@example.com"
    db.commit()

    response = client.post(
        "/api/v1/recommendations/qa",
        json={"question": "어디로 문의하면 돼?", "club_id": club.id},
    )

    assert response.json()["supported"] is True
    assert response.json()["intent"] == "contact"
    assert "club@example.com" in response.json()["answer"]


def test_recommendation_expands_related_korean_terms(client, db, seeded_club):
    db.add(
        Club(
            name="개발 연구회",
            description="코딩 스터디와 소프트웨어 프로젝트를 진행합니다.",
            is_recruiting=True,
        )
    )
    db.commit()

    response = client.post(
        "/api/v1/recommendations",
        json={"query": "프로그래밍을 배우고 싶어요", "top_k": 3},
    )

    assert response.json()["results"][0]["name"] == "개발 연구회"
    assert response.json()["results"][0]["reason"]


def test_recommendation_prioritizes_photo_club_for_photo_exhibition_query(client, db, seeded_club):
    db.add_all(
        [
            Club(
                name="사진예술연구회",
                description="사진에 관심 있는 신입 부원을 모집합니다.",
                is_recruiting=True,
            ),
            Club(
                name="야구 동아리",
                description="홍보부에서 사진과 영상 촬영을 합니다.",
                is_recruiting=True,
            ),
        ]
    )
    db.commit()

    response = client.post(
        "/api/v1/recommendations",
        json={"query": "사진 촬영을 배우고 전시회도 해보고 싶어", "top_k": 5},
    )

    results = response.json()["results"]
    assert results[0]["name"] == "사진예술연구회"


def test_recommendation_filters_semantically_broad_results_when_exact_activity_exists(
    client, db, seeded_club
):
    db.add_all(
        [
            Club(name="보드게임 모임", description="보드게임을 즐깁니다.", is_recruiting=True),
            Club(name="농구 모임", description="팀 스포츠를 즐깁니다.", is_recruiting=True),
        ]
    )
    db.commit()

    response = client.post(
        "/api/v1/recommendations",
        json={"query": "보드게임을 즐기고 싶어", "top_k": 5},
    )

    assert [result["name"] for result in response.json()["results"]] == ["보드게임 모임"]


def test_recommendation_health_reports_empty_catalog(client):
    response = client.get("/api/v1/recommendations/health")

    assert response.status_code == 200
    assert response.json()["status"] == "empty"
    assert response.json()["llm"] == {
        "enabled": False,
        "available": False,
        "model": "gemma3:4b",
    }


def test_recommendation_request_limits(client):
    response = client.post("/api/v1/recommendations", json={"query": "", "top_k": 21})

    assert response.status_code == 422

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from math import log
from threading import Lock
from typing import Any, ClassVar

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from src.core.config import settings
from src.models.club import Club
from src.services.recruitment_service import close_expired_recruitments
from src.utils.recommendation_embeddings import (
    Embedder,
    build_embedder,
    cosine_similarity,
)
from src.utils.recommendation_text import (
    keyword_tokens,
    normalize_text,
    split_sentences,
)

QUERY_STOP_WORDS = {
    "나", "난", "내", "저", "제가", "하고", "싶어", "싶어요", "싶습니다", "배우고",
    "관심", "동아리", "추천", "추천해줘", "찾아줘", "할", "수", "있는", "곳",
}
GENERIC_ACTIVITY_TERMS = ("어떤 활동", "무슨 활동", "뭐 해", "뭘 해", "하는 동아리", "소개해")
CONCEPTS = {
    "개발": ("개발", "코딩", "프로그래밍", "소프트웨어", "it", "ai", "인공지능"),
    "음악": ("음악", "밴드", "악기", "노래", "작곡", "가요", "공연"),
    "영상": ("영상", "촬영", "편집", "카메라", "콘텐츠"),
    "사진": ("사진", "촬영", "카메라", "전시"),
    "운동": ("운동", "체육", "스포츠", "경기", "대회"),
    "봉사": ("봉사", "나눔", "헌혈", "재능기부"),
    "친목": ("친목", "교류", "모임", "mt", "친구"),
    "여행": ("여행", "관광", "답사", "탐방"),
}
CONCEPT_TRIGGERS = {
    "개발": ("개발", "코딩", "프로그래밍", "소프트웨어", "ai", "인공지능"),
    "음악": ("음악", "밴드", "악기", "노래", "작곡", "가요"),
    "영상": ("영상", "편집", "콘텐츠"),
    "사진": ("사진", "전시"),
    "운동": ("운동", "체육", "스포츠", "경기", "대회"),
    "봉사": ("봉사", "나눔", "헌혈", "재능기부"),
    "친목": ("친목", "교류", "모임", "mt", "친구"),
    "여행": ("여행", "관광", "답사", "탐방"),
}
INTENT_TERMS = {
    "beginner": ("초보", "처음", "경험 없어", "못해도", "입문"),
    "recruitment": ("모집", "지원", "가입", "들어갈"),
    "contact": ("연락", "문의", "전화", "인스타", "sns", "오픈채팅"),
    "fee": ("회비", "가입비", "비용", "얼마"),
    "schedule": ("언제", "시간", "요일", "기간", "일정", "몇 시"),
    "location": ("어디", "장소", "위치"),
    "activity": (*GENERIC_ACTIVITY_TERMS, "활동", "무엇"),
}
INTENT_EVIDENCE_TERMS = {
    "fee": ("회비", "가입비", "비용"),
    "schedule": ("매주", "요일", "시간", "기간", "일정", "시", "월", "학기"),
    "location": ("장소", "위치", "관", "호", "운동장", "체육관"),
    "beginner": ("초보", "처음", "경험", "누구나", "상관없이", "환영"),
    "contact": ("연락", "문의", "전화", "인스타", "카톡", "오픈채팅"),
}


@dataclass
class ClubRecord:
    club_id: str
    name: str
    is_recruiting: bool
    text: str
    evidence: list[str]
    features: set[str]
    tokens: set[str]
    division: str | None
    activity_period: str | None
    contacts: list[str]


def _values(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _query_tokens(text: str) -> set[str]:
    words = [
        word
        for word in re.findall(r"[0-9a-z가-힣]+", normalize_text(text))
        if word not in QUERY_STOP_WORDS
    ]
    expanded = list(words)
    normalized = normalize_text(text)
    for concept in _activated_concepts(normalized):
        expanded.extend(CONCEPTS[concept])
    return set(keyword_tokens(" ".join(expanded)))


def _detect_intent(question: str) -> str:
    normalized = normalize_text(question)
    for intent, terms in INTENT_TERMS.items():
        if any(term in normalized for term in terms):
            return intent
    return "other"


def _contains_term(text: str, term: str) -> bool:
    if term.isascii() and term.isalnum():
        return re.search(rf"(?<![0-9a-z]){re.escape(term)}(?![0-9a-z])", text) is not None
    return term in text


def _activated_concepts(text: str) -> set[str]:
    concepts = {
        concept
        for concept, terms in CONCEPT_TRIGGERS.items()
        if any(_contains_term(text, term) for term in terms)
    }
    if not concepts and "촬영" in text:
        concepts = {"사진", "영상"}
    return concepts


def _specific_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for word in re.findall(r"[0-9a-z가-힣]+", normalize_text(text)):
        if word in QUERY_STOP_WORDS:
            continue
        core = word[:-1] if len(word) >= 4 and word[-1] in "을를이가은는에도과와" else word
        if len(core) >= 3:
            terms.add(core)
    return terms


def _confidence_label(score: float) -> str:
    if score >= 0.15:
        return "high"
    if score >= 0.05:
        return "medium"
    return "low"


class RecommendationService:
    _snapshot_lock: ClassVar[Lock] = Lock()
    _snapshot_key: ClassVar[tuple | None] = None
    _snapshot_records: ClassVar[list[ClubRecord]] = []
    _snapshot_vectors: ClassVar[list[list[float]]] = []
    _snapshot_evidence_vectors: ClassVar[dict[tuple[str, str], list[float]]] = {}

    def __init__(self, db: Session, embedder: Embedder | None = None) -> None:
        self.db = db
        close_expired_recruitments(db)
        self.embedder = embedder or build_embedder(
            settings.RECOMMENDATION_MODEL,
            settings.RECOMMENDATION_MODEL_CACHE_DIR or None,
        )
        count, latest_update = self.db.query(
            func.count(Club.id),
            func.max(Club.updated_at),
        ).one()
        database_key = str(self.db.get_bind().url)
        cache_key = (self.embedder.model_name, database_key, count, latest_update)
        with self._snapshot_lock:
            if cache_key != self._snapshot_key:
                records = self._load_records()
                self.__class__._snapshot_records = records
                self.__class__._snapshot_vectors = self.embedder.encode(
                    [record.text for record in records], role="passage"
                )
                evidence_items = [
                    (record.club_id, evidence)
                    for record in records
                    for evidence in record.evidence
                ]
                evidence_vectors = self.embedder.encode(
                    [evidence for _, evidence in evidence_items], role="passage"
                )
                self.__class__._snapshot_evidence_vectors = dict(
                    zip(evidence_items, evidence_vectors)
                )
                self.__class__._snapshot_key = cache_key
            self.records = self._snapshot_records
            self.vectors = self._snapshot_vectors
            self.evidence_vectors = self._snapshot_evidence_vectors

    @property
    def model_info(self) -> dict[str, str]:
        return {"model": self.embedder.model_name, "backend": self.embedder.backend}

    def _load_records(self) -> list[ClubRecord]:
        clubs = self.db.query(Club).options(selectinload(Club.tags)).order_by(Club.name).all()
        records: list[ClubRecord] = []
        for club in clubs:
            fields = [
                club.name,
                club.tagline,
                club.description,
                club.division,
                club.field,
                club.atmosphere,
                club.activity_purpose,
                club.activity_period,
            ]
            tag_values = [tag.tag_value for tag in club.tags]
            contacts = [
                value
                for value in [club.contact_email, club.contact_phone, club.open_chat_url]
                if value
            ]
            contacts.extend(
                str(link.get("value"))
                for link in (club.contact_links or [])
                if isinstance(link, dict) and link.get("value")
            )
            text_parts = [str(value) for value in fields + tag_values if value]
            evidence = split_sentences(
                "\n".join(
                    str(value)
                    for value in [
                        club.description,
                        club.tagline,
                        club.division,
                        club.field,
                        club.atmosphere,
                        club.activity_purpose,
                        club.activity_period,
                    ]
                    if value
                )
            )
            features = {normalize_text(value) for value in tag_values if value}
            records.append(
                ClubRecord(
                    club_id=club.id,
                    name=club.name,
                    is_recruiting=club.is_recruiting,
                    text=" ".join(text_parts),
                    evidence=evidence,
                    features=features,
                    tokens=set(keyword_tokens(" ".join(text_parts))),
                    division=club.division,
                    activity_period=club.activity_period,
                    contacts=list(dict.fromkeys(contacts)),
                )
            )
        return records

    def recommend(self, query: str, top_k: int, user_profile: dict[str, Any] | None = None) -> dict[str, Any]:
        profile_terms = []
        if user_profile:
            for value in user_profile.values():
                profile_terms.extend(_values(value) if isinstance(value, list) else [str(value)])
        enriched_query = " ".join([query, *profile_terms])
        query_vector = self.embedder.encode([enriched_query], role="query")[0]
        query_text = normalize_text(enriched_query)
        query_tokens = _query_tokens(query_text)
        activated_concepts = _activated_concepts(query_text)
        specific_terms = _specific_terms(query_text)
        has_exact_specific_match = not activated_concepts and any(
            term in normalize_text(record.text)
            for record in self.records
            for term in specific_terms
        )
        document_frequency = Counter(
            token for record in self.records for token in (query_tokens & record.tokens)
        )
        token_weights = {
            token: log((len(self.records) + 1) / (document_frequency[token] + 1)) + 1
            for token in query_tokens
        }
        total_query_weight = sum(token_weights.values()) or 1.0

        results = []
        for record, vector in zip(self.records, self.vectors):
            record_text = normalize_text(record.text)
            if has_exact_specific_match and not any(term in record_text for term in specific_terms):
                continue
            semantic = max(0.0, cosine_similarity(query_vector, vector))
            shared_tokens = query_tokens & record.tokens
            lexical = sum(token_weights[token] for token in shared_tokens) / total_query_weight
            concept_matches = sorted(
                concept
                for concept in activated_concepts
                if any(
                    _contains_term(record_text, term)
                    for term in CONCEPTS[concept]
                )
            )
            if activated_concepts and not concept_matches:
                continue
            matched = sorted(
                feature for feature in record.features if feature in query_text or feature in query_tokens
            )
            matched = list(dict.fromkeys([*concept_matches, *matched]))
            structured = min(1.0, len(matched) / 3.0)
            name_match = 1.0 if any(
                trigger in normalize_text(record.name)
                for concept in activated_concepts
                for trigger in CONCEPT_TRIGGERS[concept]
                if len(trigger) >= 2
            ) else 0.0
            # The lexical component is deliberately strong: it keeps the local
            # hashing fallback useful for Korean queries while a transformer is
            # unavailable, instead of assigning every unrelated club ~0.5.
            score = semantic * 0.1 + lexical * 0.5 + structured * 0.2 + name_match * 0.3
            results.append(
                {
                    "club_id": record.club_id,
                    "name": record.name,
                    "score": round(min(score, 1.0), 4),
                    "matched_constraints": matched,
                    "evidence": record.evidence[:2],
                    "is_recruiting": record.is_recruiting,
                    "confidence": _confidence_label(score),
                    "reason": (
                        f"{', '.join(matched[:3])} 관심사와 관련된 활동 정보가 있습니다."
                        if matched
                        else "소개 내용의 의미가 입력한 관심사와 유사합니다."
                    ),
                }
            )
        results.sort(key=lambda item: item["score"], reverse=True)
        if results:
            relevance_floor = max(0.03, results[0]["score"] * 0.55)
            results = [result for result in results if result["score"] >= relevance_floor]
        return {"query": query, "results": results[:top_k], "model_info": self.model_info}

    def qa(
        self,
        question: str,
        club_id: str | None = None,
        previous_question: str | None = None,
    ) -> dict[str, Any]:
        candidates = [record for record in self.records if club_id is None or record.club_id == club_id]
        if club_id and not candidates:
            raise LookupError("동아리를 찾을 수 없습니다.")
        intent = _detect_intent(question)
        if intent == "other" and previous_question:
            intent = _detect_intent(previous_question)
        suggestions = ["어떤 활동을 하나요?", "초보도 가능한가요?", "지금 모집 중인가요?"]

        if club_id and intent == "activity" and candidates[0].evidence:
            evidence = candidates[0].evidence[:2]
            return {
                "supported": True,
                "answer": " ".join(evidence),
                "club_id": club_id,
                "evidence": evidence,
                "model_info": self.model_info,
                "intent": intent,
                "confidence": 0.8,
                "suggested_questions": suggestions,
            }

        if club_id and intent == "recruitment":
            answer = "현재 모집 중입니다." if candidates[0].is_recruiting else "현재는 모집 중이 아닙니다."
            return {
                "supported": True,
                "answer": answer,
                "club_id": club_id,
                "evidence": [answer],
                "model_info": self.model_info,
                "intent": intent,
                "confidence": 1.0,
                "suggested_questions": suggestions,
            }

        if club_id and intent == "contact" and candidates[0].contacts:
            answer = "공개된 문의 채널은 " + ", ".join(candidates[0].contacts[:3]) + " 입니다."
            return {
                "supported": True,
                "answer": answer,
                "club_id": club_id,
                "evidence": candidates[0].contacts[:3],
                "model_info": self.model_info,
                "intent": intent,
                "confidence": 1.0,
                "suggested_questions": suggestions,
            }

        enriched_question = " ".join(filter(None, [previous_question, question]))
        question_vector = self.embedder.encode([enriched_question], role="query")[0]
        question_tokens = _query_tokens(enriched_question)
        scored: list[tuple[float, ClubRecord, str]] = []
        for record in candidates:
            for evidence in record.evidence:
                vector = self.evidence_vectors[(record.club_id, evidence)]
                semantic_score = max(0.0, cosine_similarity(question_vector, vector))
                evidence_tokens = set(keyword_tokens(evidence))
                shared_tokens = question_tokens & evidence_tokens
                lexical_score = len(shared_tokens) / max(1, min(len(question_tokens), 24))
                intent_bonus = 0.0
                if intent in INTENT_EVIDENCE_TERMS and any(
                    term in normalize_text(evidence) for term in INTENT_EVIDENCE_TERMS[intent]
                ):
                    intent_bonus = 0.35
                score = semantic_score * 0.35 + lexical_score * 0.65 + intent_bonus
                scored.append((min(score, 1.0), record, evidence))
        scored.sort(key=lambda item: item[0], reverse=True)
        threshold = settings.RECOMMENDATION_QA_THRESHOLD
        if intent == "activity":
            threshold = min(threshold, 0.08)
        if not scored or scored[0][0] < threshold:
            contact_hint = " 공개된 연락처로 문의해 주세요." if club_id and candidates[0].contacts else ""
            return {
                "supported": False,
                "answer": "현재 등록된 동아리 정보만으로는 확인할 수 없습니다." + contact_hint,
                "club_id": club_id,
                "evidence": [],
                "model_info": self.model_info,
                "intent": intent,
                "confidence": round(scored[0][0], 3) if scored else 0.0,
                "suggested_questions": suggestions,
            }
        best_score, best_record, _ = scored[0]
        evidence = [
            text
            for score, record, text in scored
            if record.club_id == best_record.club_id and score >= best_score - 0.05
        ][:2]
        return {
            "supported": True,
            "answer": " ".join(evidence),
            "club_id": best_record.club_id,
            "evidence": evidence,
            "model_info": self.model_info,
            "intent": intent,
            "confidence": round(best_score, 3),
            "suggested_questions": suggestions,
        }

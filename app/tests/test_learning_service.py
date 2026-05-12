from datetime import datetime, timedelta
from types import SimpleNamespace

from app.learning import service as learning_service_module
from app.learning.service import LearningService


def test_generate_cards_from_normal_answer():
    service = LearningService()
    text = (
        "При подозрении на панкреатит у собаки оценивают дегидратацию и электролиты. "
        "Базовая терапия включает инфузию, анальгезию и ранний контроль боли. "
        "Антибиотики назначают по показаниям, а не рутинно."
    )
    cards = service.generate_cards(text=text, topic_id="t1", source_message_id="m1", tags=["answer"], user_id="u1", count=6)
    assert len(cards) >= 3
    assert all(card.front and card.back for card in cards)
    assert all(card.source_message_id == "m1" for card in cards)
    assert all("answer" in card.tags for card in cards)


def test_review_flow_updates_due_interval_and_ease():
    service = LearningService()
    now = datetime(2026, 1, 1, 10, 0, 0)
    card = SimpleNamespace(ease=2.5, interval_days=1, due_at=now, tags=[])
    known, score_known = service.apply_review(card=card, action="known", now=now)
    assert score_known == 4
    assert known.interval_days >= 2
    assert known.due_at == now + timedelta(days=known.interval_days)
    unknown, score_unknown = service.apply_review(card=known, action="unknown", now=now)
    assert score_unknown == 1
    assert unknown.interval_days == 1
    later, score_later = service.apply_review(card=unknown, action="later", now=now)
    assert score_later == 2
    assert later.interval_days >= 1
    assert "leech" not in (later.tags or [])

    unknown2, score_unknown2 = service.apply_review(card=later, action="unknown", now=now)
    assert unknown2.lapses == 2
    assert "leech" in (unknown2.tags or [])


def test_anki_csv_export_escapes_commas_and_newlines():
    service = LearningService()
    card = SimpleNamespace(
        front='Front, "quoted"\nline2',
        back="Back,\nmultiline",
        tags=["tag1", "tag2"],
        source_message_id="msg-1",
    )
    csv_data = service.export_anki_csv([card])
    assert '"front","back","tags","source"' in csv_data
    assert '"Front, ""quoted""' in csv_data
    assert "line2" in csv_data
    assert '"Back,\nmultiline"' in csv_data


def test_normalize_cards_deduplicates_and_validates():
    service = LearningService()
    payload = {
        "cards": [
            {"front": "Что делать при дегидратации?", "back": "Оценить степень и начать инфузию.", "difficulty": "easy", "tags": ["fluid"], "card_type": "case_next_step", "needs_manual_check": True},
            {"front": "Что делать при дегидратации?", "back": "Оценить степень и начать инфузию.", "difficulty": "easy", "tags": ["fluid"]},
            {"front": "short", "back": "too short"},
        ]
    }
    items = service._normalize_card_payload(payload, count=5, tags=["cards"])
    assert len(items) == 1
    assert items[0]["difficulty"] == "easy"
    assert "cards" in items[0]["tags"]
    assert items[0]["card_type"] == "case_next_step"
    assert items[0]["needs_manual_check"] is True


class _FakeResult:
    def __init__(self, *, scalar=None, row=None):
        self._scalar = scalar
        self._row = row

    def scalar_one(self):
        return self._scalar

    def one_or_none(self):
        return self._row

    def all(self):
        return self._row or []


class _FakeDB:
    def __init__(self, results):
        self._results = list(results)
        self._idx = 0

    def execute(self, _stmt):
        result = self._results[self._idx]
        self._idx += 1
        return result


def test_build_daily_route_fallback_when_no_cards(monkeypatch):
    service = LearningService()

    class _Repo:
        def __init__(self, _db):
            pass

        def list_due(self, **kwargs):
            return []

        def by_user(self, *args, **kwargs):
            return []

    monkeypatch.setattr(learning_service_module, "FlashcardRepo", _Repo)
    db = _FakeDB(
        [
            _FakeResult(scalar=0),
            _FakeResult(scalar=0),
            _FakeResult(row=[]),
            _FakeResult(scalar=0),
            _FakeResult(scalar=0),
            _FakeResult(row=[]),
            _FakeResult(row=[]),
            _FakeResult(row=[]),
            _FakeResult(row=("Терапия",)),
        ]
    )
    route = service.build_daily_route(db=db, user_id="u-1", topic_id="t-1", now=datetime(2026, 5, 3, 10, 0, 0))
    assert route.used_fallback is True
    assert route.mode == "standard"
    assert route.due_count == 0
    assert len(route.review_cards) == 3
    assert "НПВС у кошек" in route.drug_risk
    assert route.zero_result_searches == 0
    assert route.negative_feedback_count == 0
    assert route.high_risk_block_count == 0


def test_build_daily_route_from_existing_cards(monkeypatch):
    service = LearningService()
    due_cards = [
        SimpleNamespace(front="Кошка с рвотой: первый шаг?", back="Оценить triage и дегидратацию."),
        SimpleNamespace(front="Какие red flags при диарее?", back="Кровь, вялость, обезвоживание."),
    ]
    all_cards = [*due_cards, SimpleNamespace(front="НПВС у кошек: риск?", back="Почки, GI, стероиды.")]

    class _Repo:
        def __init__(self, _db):
            pass

        def list_due(self, **kwargs):
            return due_cards

        def by_user(self, *args, **kwargs):
            return all_cards

    monkeypatch.setattr(learning_service_module, "FlashcardRepo", _Repo)
    db = _FakeDB(
        [
            _FakeResult(scalar=1),
            _FakeResult(scalar=2),
            _FakeResult(row=[({"results": 0},)]),
            _FakeResult(scalar=1),
            _FakeResult(scalar=4),
            _FakeResult(row=[("Терапия", 2)]),
            _FakeResult(row=[({"kind": "provider"},)]),
            _FakeResult(row=[({"difficulty": "basic"},)]),
            _FakeResult(row=("Терапия",)),
        ]
    )
    route = service.build_daily_route(db=db, user_id="u-1", topic_id="t-1", now=datetime(2026, 5, 3, 10, 0, 0), mode="intensive")
    assert route.used_fallback is False
    assert route.mode == "intensive"
    assert route.due_count == 2
    assert len(route.review_cards) == 3  # capped by available cards
    assert "Мини-кейс" in route.mini_case
    assert route.zero_result_searches == 1
    assert route.negative_feedback_count == 1
    assert route.high_risk_block_count == 4
    assert "Терапия" in route.weak_topics
    assert "recent_error:provider" in route.weak_topics


def test_build_week_plan(monkeypatch):
    service = LearningService()

    monkeypatch.setattr(
        LearningService,
        "build_daily_route",
        lambda self, **kwargs: SimpleNamespace(
            mode="standard",
            plan_minutes=25,
            mini_case="Собака с рвотой",
            drug_risk="НПВС",
            due_count=4,
            review_cards=["Q1", "Q2", "Q3"],
            reflection_question="R",
            used_fallback=False,
            weak_topics=["Терапия"],
            zero_result_searches=1,
            negative_feedback_count=0,
            high_risk_block_count=0,
        ),
    )
    monkeypatch.setattr(LearningService, "compute_streak", lambda self, **kwargs: (5, 2))
    plan = service.build_week_plan(db=object(), user_id="u-1", topic_id="t-1", now=datetime(2026, 5, 3, 10, 0, 0))
    assert len(plan.days) == 7
    assert plan.streak_days == 5
    assert "/case" in plan.days[0].planned_commands


def test_build_weekly_recap_counts(monkeypatch):
    service = LearningService()
    db = _FakeDB(
        [
            _FakeResult(scalar=5),
            _FakeResult(scalar=8),
            _FakeResult(scalar=2),
            _FakeResult(scalar=11),
            _FakeResult(row=[("Терапия", 3), ("Кардио", 1)]),
        ]
    )
    recap = service.build_weekly_recap(db=db, user_id="u-1", now=datetime(2026, 5, 3, 10, 0, 0))
    assert recap.cards_created == 5
    assert recap.cards_reviewed == 8
    assert recap.high_risk_queries == 2
    assert recap.questions_asked == 11
    assert recap.weak_topics == ["Терапия", "Кардио"]

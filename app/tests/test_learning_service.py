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
    db = _FakeDB([_FakeResult(scalar=0), _FakeResult(scalar=0), _FakeResult(row=("Терапия",))])
    route = service.build_daily_route(db=db, user_id="u-1", topic_id="t-1", now=datetime(2026, 5, 3, 10, 0, 0))
    assert route.used_fallback is True
    assert route.due_count == 0
    assert len(route.review_cards) == 3
    assert "НПВС у кошек" in route.drug_risk


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
    db = _FakeDB([_FakeResult(scalar=1), _FakeResult(scalar=2), _FakeResult(row=("Терапия",))])
    route = service.build_daily_route(db=db, user_id="u-1", topic_id="t-1", now=datetime(2026, 5, 3, 10, 0, 0))
    assert route.used_fallback is False
    assert route.due_count == 2
    assert len(route.review_cards) == 3
    assert "Мини-кейс" in route.mini_case

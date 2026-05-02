from datetime import datetime, timedelta
from types import SimpleNamespace

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
    card = SimpleNamespace(ease=2.5, interval_days=1, due_at=now)
    known = service.apply_review(card=card, action="known", now=now)
    assert known.interval_days >= 2
    assert known.due_at == now + timedelta(days=known.interval_days)
    unknown = service.apply_review(card=known, action="unknown", now=now)
    assert unknown.interval_days == 1
    later = service.apply_review(card=unknown, action="later", now=now)
    assert later.interval_days >= 1


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

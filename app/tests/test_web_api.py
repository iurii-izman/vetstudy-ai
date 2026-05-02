from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.models import Base, Document, DocumentChunk, ErrorEvent, Flashcard, MemoryItem, Message, ModelCall, Session, Subject, Topic, User
from app.db.session import get_db
from app.main import app


def make_client():
    engine = create_engine(
        'sqlite+pysqlite:///:memory:',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    db = SessionLocal()
    owner = User(telegram_user_id=999, display_name='Owner', role='owner')
    user1 = User(telegram_user_id=1001, display_name='U1', role='user')
    user2 = User(telegram_user_id=1002, display_name='U2', role='user')
    subj = Subject(slug='surgery', title='Surgery', system_prompt='Surgery')
    db.add_all([owner, user1, user2, subj])
    db.flush()
    topic1 = Topic(telegram_chat_id=1, telegram_thread_id=10, title='Fractures', summary='Topic summary', user_id=user1.id)
    topic2 = Topic(telegram_chat_id=2, telegram_thread_id=20, title='Cardio', summary='Cardio summary', user_id=user2.id)
    topic3 = Topic(telegram_chat_id=3, telegram_thread_id=30, title='Telegram Global', summary='Shared forum topic', user_id=None)
    db.add_all([topic1, topic2, topic3])
    db.flush()
    sess1 = Session(mode='practical', user_id=user1.id, topic_id=topic1.id)
    sess2 = Session(mode='practical', user_id=user2.id, topic_id=topic2.id)
    sess3 = Session(mode='practical', user_id=user1.id, topic_id=topic3.id, is_active=False)
    db.add_all([sess1, sess2, sess3])
    db.flush()
    msg1 = Message(role='assistant', content='U1 answer', session_id=sess1.id)
    msg2 = Message(role='assistant', content='U2 answer', session_id=sess2.id)
    db.add_all([msg1, msg2])
    db.flush()
    note1 = MemoryItem(kind='note', title='Note', content='U1 note', tags=['ortho'], user_id=user1.id, topic_id=topic1.id, source_message_id=msg1.id)
    note2 = MemoryItem(kind='note', title='Note', content='U2 note', tags=['cardio'], user_id=user2.id, topic_id=topic2.id, source_message_id=msg2.id)
    card1 = Flashcard(front='Q1', back='A1', due_at=datetime.now(UTC), user_id=user1.id, topic_id=topic1.id)
    card2 = Flashcard(front='Q2', back='A2', due_at=datetime.now(UTC), user_id=user2.id, topic_id=topic2.id)
    call1 = ModelCall(user_id=user1.id, provider='mock', model='m1', purpose='answer', input_tokens=10, output_tokens=20, cost_usd=0.1)
    err1 = ErrorEvent(user_id=user1.id, scope='api', category='test', details={'x': 1})

    db.add_all([note1, note2, card1, card2, call1, err1])
    db.flush()
    doc = Document(user_id=user1.id, topic_id=topic1.id, filename="u1.pdf", size_bytes=100, status="indexed", job_id="job-u1", metadata_={})
    db.add(doc)
    db.flush()
    chunk = DocumentChunk(document_id=doc.id, user_id=user1.id, topic_id=topic1.id, chunk_index=0, chunk_hash="h1", content="U1 chunk", snippet="U1 chunk", tags=["document"], embedding=None, metadata_={})
    db.add(chunk)
    db.commit()
    topic1_id = topic1.id
    topic2_id = topic2.id
    db.close()

    return TestClient(app), topic1_id, topic2_id


def _owner_headers():
    return {'Authorization': f'Bearer {get_settings().web_owner_token}', 'X-User-Telegram-Id': '999'}


def _user_headers(tg_id: int):
    return {'Authorization': f'Bearer {get_settings().web_owner_token}', 'X-User-Telegram-Id': str(tg_id)}


def test_web_auth_and_stats_user_scoped():
    client, _, _ = make_client()
    auth = client.post('/api/web/auth/login', json={'password': get_settings().web_owner_password})
    assert auth.status_code == 200

    stats = client.get('/api/web/stats', headers=_user_headers(1001))
    assert stats.status_code == 200
    assert stats.json()['topics_total'] == 2


def test_web_lists_telegram_global_topics_used_by_user():
    client, _, _ = make_client()
    res = client.get('/api/web/topics', headers=_user_headers(1001))
    assert res.status_code == 200
    titles = {item['title'] for item in res.json()}
    assert titles == {'Fractures', 'Telegram Global'}


def test_web_requires_bearer_token_for_user_endpoints():
    client, _, _ = make_client()
    res = client.get('/api/web/stats', headers={'X-User-Telegram-Id': '1001'})
    assert res.status_code == 401


def test_owner_token_can_use_web_without_user_header():
    client, _, _ = make_client()
    res = client.get('/api/web/stats', headers={'Authorization': f'Bearer {get_settings().web_owner_token}'})
    assert res.status_code == 200


def test_user_isolation_topics_notes_messages_flashcards_search():
    client, topic1_id, topic2_id = make_client()

    notes = client.get(f'/api/web/notes?topic_id={topic1_id}', headers=_user_headers(1001))
    assert notes.status_code == 200
    assert len(notes.json()) == 1
    assert notes.json()[0]['content'] == 'U1 note'

    notes_other = client.get(f'/api/web/notes?topic_id={topic2_id}', headers=_user_headers(1001))
    assert notes_other.status_code == 200
    assert notes_other.json() == []

    messages = client.get('/api/web/messages', headers=_user_headers(1001))
    assert messages.status_code == 200
    assert len(messages.json()) == 1
    assert messages.json()[0]['content'] == 'U1 answer'

    cards = client.get('/api/web/flashcards', headers=_user_headers(1001))
    assert cards.status_code == 200
    assert len(cards.json()) == 1
    assert cards.json()[0]['front'] == 'Q1'

    res = client.get('/api/web/memory/search?q=note', headers=_user_headers(1001))
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]['content'] == 'U1 note'


def test_onboarding_export_and_delete_topic():
    client, topic1_id, _ = make_client()

    onboard = client.post(
        '/api/web/onboarding',
        headers=_user_headers(1001),
        json={'language': 'en', 'specialization': 'surgery', 'subjects': ['surgery', 'diagnostics']},
    )
    assert onboard.status_code == 200

    profile = client.get('/api/web/me', headers=_user_headers(1001))
    assert profile.status_code == 200
    assert profile.json()['onboarding_completed'] is True

    exported = client.get('/api/web/privacy/export', headers=_user_headers(1001))
    assert exported.status_code == 200
    assert len(exported.json()['messages']) == 1
    assert len(exported.json()['documents']) == 1
    assert len(exported.json()['document_chunks']) == 1

    deleted = client.delete(f'/api/web/privacy/topic/{topic1_id}', headers=_user_headers(1001))
    assert deleted.status_code == 200

    notes_after = client.get('/api/web/notes', headers=_user_headers(1001))
    assert notes_after.status_code == 200
    assert notes_after.json() == []
    exported_after = client.get('/api/web/privacy/export', headers=_user_headers(1001))
    assert exported_after.status_code == 200
    assert exported_after.json()["documents"] == []


def test_admin_usage_costs_errors_and_users():
    client, _, _ = make_client()

    users = client.get('/api/web/admin/users', headers=_owner_headers())
    assert users.status_code == 200
    assert len(users.json()) >= 3

    usage = client.get('/api/web/admin/usage', headers=_owner_headers())
    assert usage.status_code == 200
    assert usage.json()['calls'] >= 1

    costs = client.get('/api/web/admin/costs', headers=_owner_headers())
    assert costs.status_code == 200
    assert len(costs.json()) >= 1

    errors = client.get('/api/web/admin/errors', headers=_owner_headers())
    assert errors.status_code == 200
    assert len(errors.json()) >= 1

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.models import Base, Document, DocumentChunk, ErrorEvent, FeedbackEvent, Flashcard, MemoryItem, Message, ModelCall, ProductEvent, Session, Subject, Topic, User
from app.db.session import get_db
from app.main import app
from app.web.router import SESSION_COOKIE, _rate_limiter
from app.web.security import hash_password


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
    msg1 = Message(
        role='assistant',
        content='U1 answer',
        session_id=sess1.id,
        metadata_={
            "high_risk": True,
            "safety": {"intent": "dosage_request", "risk_tags": ["dosage_request"]},
            "evidence": {
                "status": "needs_manual_check",
                "verification_status": "needs_manual_check",
                "trust_indicators": ["src:official | trust:high | verify:needs_manual_check"],
                "source_class": "official",
                "trust_level": "high",
                "needs_manual_check": True,
                "manual_check_reasons": ["Need exact product concentration."],
                "next_questions": ["Species and weight?"],
            },
            "why_trace": {
                "missing_data": ["Species and weight?"],
            },
        },
    )
    msg2 = Message(role='assistant', content='U2 answer', session_id=sess2.id)
    db.add_all([msg1, msg2])
    db.flush()
    note1 = MemoryItem(kind='note', title='Note', content='U1 note', tags=['ortho'], user_id=user1.id, topic_id=topic1.id, source_message_id=msg1.id)
    note2 = MemoryItem(kind='note', title='Note', content='U2 note', tags=['cardio'], user_id=user2.id, topic_id=topic2.id, source_message_id=msg2.id)
    card1 = Flashcard(front='Q1', back='A1', due_at=datetime.now(UTC), user_id=user1.id, topic_id=topic1.id)
    card2 = Flashcard(front='Q2', back='A2', due_at=datetime.now(UTC), user_id=user2.id, topic_id=topic2.id)
    call1 = ModelCall(user_id=user1.id, provider='mock', model='m1', purpose='answer', input_tokens=10, output_tokens=20, cost_usd=0.1)
    err1 = ErrorEvent(user_id=user1.id, scope='api', category='test', details={'x': 1})

    feedback = FeedbackEvent(user_id=user1.id, topic_id=topic1.id, message_id=msg1.id, source_message_id=msg1.id, feedback_type="down", status="new", metadata_={})
    ev1 = ProductEvent(user_id=user1.id, topic_id=topic1.id, session_id=sess1.id, event_name="activation_start", properties={})
    ev2 = ProductEvent(user_id=user1.id, topic_id=topic1.id, session_id=sess1.id, event_name="high_risk_query", properties={})
    ev3 = ProductEvent(user_id=user1.id, topic_id=topic1.id, session_id=sess1.id, event_name="retrieval_context_built", properties={"results": 2, "memory_hits": 1, "document_hits": 1})
    db.add_all([note1, note2, card1, card2, call1, err1, feedback, ev1, ev2, ev3])
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


def test_session_token_cannot_impersonate_other_user_with_header():
    client, _, _ = make_client()
    auth = client.post('/api/web/auth/login', json={'password': get_settings().web_owner_password})
    assert auth.status_code == 200
    token = auth.json()["access_token"]

    res = client.get(
        '/api/web/stats',
        headers={'Authorization': f'Bearer {token}', 'X-User-Telegram-Id': '1001'},
    )
    assert res.status_code == 403


def test_malformed_bearer_token_returns_401():
    client, _, _ = make_client()
    res = client.get('/api/web/stats', headers={'Authorization': 'Bearer not-a-valid-session-token'})
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid session token"


def test_invalid_x_user_telegram_id_rejected():
    client, _, _ = make_client()
    res = client.get('/api/web/stats', headers={'Authorization': f'Bearer {get_settings().web_owner_token}', 'X-User-Telegram-Id': '0'})
    assert res.status_code == 400


def test_owner_token_can_use_web_without_user_header():
    client, _, _ = make_client()
    settings = get_settings()
    old_owner_id = settings.web_owner_telegram_id
    try:
        settings.web_owner_telegram_id = 999
        res = client.get('/api/web/stats', headers={'Authorization': f'Bearer {settings.web_owner_token}'})
        assert res.status_code == 200
    finally:
        settings.web_owner_telegram_id = old_owner_id


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
    assert "provider" in costs.json()[0]

    errors = client.get('/api/web/admin/errors', headers=_owner_headers())
    assert errors.status_code == 200
    assert len(errors.json()) >= 1
    feedback = client.get('/api/web/admin/feedback', headers=_owner_headers())
    assert feedback.status_code == 200
    assert len(feedback.json()) >= 1
    feedback_id = feedback.json()[0]["id"]
    updated = client.patch(f"/api/web/admin/feedback/{feedback_id}", headers=_owner_headers(), json={"status": "in_review"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_review"


def test_flashcard_review_endpoint_creates_event():
    client, topic1_id, _ = make_client()
    cards = client.get(f'/api/web/flashcards?topic_id={topic1_id}', headers=_user_headers(1001))
    card_id = cards.json()[0]["id"]
    review = client.post(f'/api/web/flashcards/{card_id}/review', headers=_user_headers(1001), json={"action": "good"})
    assert review.status_code == 200
    assert review.json()["interval_days"] >= 1


def test_admin_evidence_endpoints():
    client, _, _ = make_client()
    coverage = client.get('/api/web/admin/evidence/source-coverage', headers=_owner_headers())
    assert coverage.status_code == 200
    assert "total_sources" in coverage.json()

    needs = client.get('/api/web/admin/evidence/needs-check', headers=_owner_headers())
    assert needs.status_code == 200
    trace = client.get('/api/web/admin/trust-safety-trace', headers=_owner_headers())
    assert trace.status_code == 200
    assert trace.json()
    assert trace.json()[0]["risk_intent"] == "dosage_request"
    assert "trust_trace_compact" in trace.json()[0]


def test_search_facets_and_topic_graph():
    client, topic1_id, _ = make_client()
    res = client.get(f'/api/web/memory/search?q=note&kind=note&tag=ortho&topic_id={topic1_id}', headers=_user_headers(1001))
    assert res.status_code == 200
    assert len(res.json()) == 1
    graph = client.get('/api/web/topics/graph', headers=_user_headers(1001))
    assert graph.status_code == 200
    assert "nodes" in graph.json()


def test_web_login_supports_password_hash_and_refresh():
    client, _, _ = make_client()
    settings = get_settings()
    old_hash = settings.web_owner_password_hash
    old_owner_id = settings.web_owner_telegram_id
    try:
        settings.web_owner_telegram_id = 999
        settings.web_owner_password_hash = hash_password("secure-pass-1")
        auth = client.post("/api/web/auth/session", json={"password": "secure-pass-1"})
        assert auth.status_code == 200
        assert "access_token" in auth.json()
        assert SESSION_COOKIE in auth.cookies
        client.cookies.set(SESSION_COOKIE, auth.cookies.get(SESSION_COOKIE))
        refreshed = client.post("/api/web/auth/refresh")
        assert refreshed.status_code == 200
        assert refreshed.json()["access_token"] != auth.json()["access_token"]
    finally:
        settings.web_owner_password_hash = old_hash
        settings.web_owner_telegram_id = old_owner_id


def test_web_login_rate_limit_and_admin_alert_endpoints():
    client, _, _ = make_client()
    _rate_limiter.reset()
    settings = get_settings()
    old_count = settings.web_login_rate_limit_count
    old_window = settings.web_login_rate_limit_window_seconds
    old_owner_id = settings.web_owner_telegram_id
    try:
        settings.web_owner_telegram_id = 999
        settings.web_login_rate_limit_count = 1
        settings.web_login_rate_limit_window_seconds = 60
        ok = client.post("/api/web/auth/login", json={"password": settings.web_owner_password})
        assert ok.status_code == 200
        limited = client.post("/api/web/auth/login", json={"password": settings.web_owner_password})
        assert limited.status_code == 429
    finally:
        settings.web_login_rate_limit_count = old_count
        settings.web_login_rate_limit_window_seconds = old_window
        settings.web_owner_telegram_id = old_owner_id

    metrics = client.get("/api/web/admin/metrics/providers", headers=_owner_headers())
    assert metrics.status_code == 200
    assert isinstance(metrics.json(), list)
    alerts = client.get("/api/web/admin/alerts/unanswered", headers=_owner_headers())
    assert alerts.status_code == 200
    cost_alert = client.get("/api/web/admin/alerts/cost-budget", headers=_owner_headers())
    assert cost_alert.status_code == 200
    assert "alert_level" in cost_alert.json()


def test_admin_cost_budget_alert_can_be_critical():
    client, _, _ = make_client()
    settings = get_settings()
    old_budget = settings.weekly_cost_budget_usd
    old_ratio = settings.weekly_cost_alarm_ratio
    try:
        settings.weekly_cost_budget_usd = 0.05
        settings.weekly_cost_alarm_ratio = 0.8
        alert = client.get("/api/web/admin/alerts/cost-budget", headers=_owner_headers())
        assert alert.status_code == 200
        body = alert.json()
        assert body["alert_level"] == "critical"
        assert body["cost_usd_current_week"] >= 0.1
        assert body["weekly_budget_usd"] == 0.05
    finally:
        settings.weekly_cost_budget_usd = old_budget
        settings.weekly_cost_alarm_ratio = old_ratio


def test_profile_endpoints_and_admin_analytics_summary():
    client, _, _ = make_client()
    current = client.get("/api/web/profile", headers=_user_headers(1001))
    assert current.status_code == 200
    assert current.json()["region"] == "unspecified"

    updated = client.patch("/api/web/profile", headers=_user_headers(1001), json={"region": "eu", "species_focus": "cat"})
    assert updated.status_code == 200
    assert updated.json()["region"] == "eu"

    summary = client.get("/api/web/admin/analytics/summary", headers=_owner_headers())
    assert summary.status_code == 200
    assert "activation_funnel" in summary.json()
    assert "journey_health" in summary.json()
    assert "content_gap_report" in summary.json()
    assert "retrieval_quality" in summary.json()
    journey = client.get("/api/web/admin/analytics/journey-health", headers=_owner_headers())
    assert journey.status_code == 200
    assert "drop_points" in journey.json()
    retrieval = client.get("/api/web/admin/analytics/retrieval-quality", headers=_owner_headers())
    assert retrieval.status_code == 200
    assert "retrieval_hit_rate" in retrieval.json()


def test_privacy_topic_delete_removes_raw_upload_file(tmp_path):
    client, topic1_id, _ = make_client()
    settings = get_settings()
    upload_base = tmp_path / "uploads"
    upload_base.mkdir(parents=True, exist_ok=True)
    old_media_storage = settings.media_storage_path
    settings.media_storage_path = str(upload_base)
    upload = upload_base / "upload-topic.pdf"
    upload.write_text("sensitive", encoding="utf-8")
    try:
        with client as c:
            db = next(app.dependency_overrides[get_db]())
            try:
                user = db.query(User).filter(User.telegram_user_id == 1001).one()
                topic = db.query(Topic).filter(Topic.id == topic1_id).one()
                doc = Document(user_id=user.id, topic_id=topic.id, filename="upload-topic.pdf", size_bytes=9, status="indexed", job_id="job-topic-raw", metadata_={"stored_path": str(upload)})
                db.add(doc)
                db.commit()
            finally:
                db.close()
            deleted = c.delete(f"/api/web/privacy/topic/{topic1_id}", headers=_user_headers(1001))
            assert deleted.status_code == 200
        assert not upload.exists()
    finally:
        settings.media_storage_path = old_media_storage


def test_privacy_account_delete_is_idempotent_when_file_missing(tmp_path):
    client, _, _ = make_client()
    settings = get_settings()
    upload_base = tmp_path / "uploads"
    upload_base.mkdir(parents=True, exist_ok=True)
    old_media_storage = settings.media_storage_path
    settings.media_storage_path = str(upload_base)
    missing = upload_base / "missing-account.pdf"
    try:
        with client as c:
            db = next(app.dependency_overrides[get_db]())
            try:
                user = db.query(User).filter(User.telegram_user_id == 1002).one()
                doc = Document(user_id=user.id, topic_id=None, filename="missing-account.pdf", size_bytes=0, status="indexed", job_id="job-account-raw", metadata_={"stored_path": str(missing)})
                db.add(doc)
                db.commit()
            finally:
                db.close()
            deleted = c.delete("/api/web/privacy/account", headers=_user_headers(1002))
            assert deleted.status_code == 200
    finally:
        settings.media_storage_path = old_media_storage


def test_privacy_topic_delete_does_not_remove_outside_storage(tmp_path):
    client, topic1_id, _ = make_client()
    settings = get_settings()
    upload_base = tmp_path / "uploads"
    upload_base.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.pdf"
    outside.write_text("outside", encoding="utf-8")
    old_media_storage = settings.media_storage_path
    settings.media_storage_path = str(upload_base)
    try:
        with client as c:
            db = next(app.dependency_overrides[get_db]())
            try:
                user = db.query(User).filter(User.telegram_user_id == 1001).one()
                topic = db.query(Topic).filter(Topic.id == topic1_id).one()
                doc = Document(user_id=user.id, topic_id=topic.id, filename="outside.pdf", size_bytes=7, status="indexed", job_id="job-topic-outside", metadata_={"stored_path": str(outside)})
                db.add(doc)
                db.commit()
            finally:
                db.close()
            deleted = c.delete(f"/api/web/privacy/topic/{topic1_id}", headers=_user_headers(1001))
            assert deleted.status_code == 200
        assert outside.exists()
    finally:
        settings.media_storage_path = old_media_storage


def test_redis_rate_limiter_falls_back_to_memory_on_redis_error(monkeypatch):
    client, _, _ = make_client()
    settings = get_settings()
    _rate_limiter.reset()
    old_count = settings.web_login_rate_limit_count
    old_window = settings.web_login_rate_limit_window_seconds
    old_owner_id = settings.web_owner_telegram_id
    try:
        settings.web_owner_telegram_id = 999
        settings.web_login_rate_limit_count = 1
        settings.web_login_rate_limit_window_seconds = 60
        monkeypatch.setattr(_rate_limiter, "_redis", SimpleNamespace(pipeline=lambda: (_ for _ in ()).throw(RuntimeError("redis down"))))
        ok = client.post("/api/web/auth/login", json={"password": settings.web_owner_password})
        limited = client.post("/api/web/auth/login", json={"password": settings.web_owner_password})
        assert ok.status_code == 200
        assert limited.status_code == 429
    finally:
        settings.web_login_rate_limit_count = old_count
        settings.web_login_rate_limit_window_seconds = old_window
        settings.web_owner_telegram_id = old_owner_id


def test_admin_endpoints_are_rate_limited():
    client, _, _ = make_client()
    settings = get_settings()
    old_count = settings.web_admin_rate_limit_count
    old_window = settings.web_admin_rate_limit_window_seconds
    try:
        settings.web_admin_rate_limit_count = 1
        settings.web_admin_rate_limit_window_seconds = 60
        _rate_limiter.reset()
        first = client.get("/api/web/admin/errors", headers=_owner_headers())
        second = client.get("/api/web/admin/errors", headers=_owner_headers())
        assert first.status_code == 200
        assert second.status_code == 429
    finally:
        settings.web_admin_rate_limit_count = old_count
        settings.web_admin_rate_limit_window_seconds = old_window

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.models import Base, User
from app.db.session import get_db
from app.main import app


def _make_client():
    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
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
    db.add_all([
        User(telegram_user_id=999, display_name='Owner', role='owner'),
        User(telegram_user_id=1001, display_name='User', role='user'),
    ])
    db.commit()
    db.close()
    return TestClient(app)


def test_user_cannot_access_admin_usage():
    client = _make_client()
    res = client.get('/api/web/admin/usage', headers={'Authorization': f'Bearer {get_settings().web_owner_token}', 'X-User-Telegram-Id': '1001'})
    assert res.status_code == 403


def test_session_cookie_user_mismatch_is_rejected():
    client = _make_client()
    settings = get_settings()
    old_owner_id = settings.web_owner_telegram_id
    try:
        settings.web_owner_telegram_id = 999
        auth = client.post('/api/web/auth/session', json={'password': settings.web_owner_password})
        assert auth.status_code == 200
        token = auth.cookies.get('vetstudy_session')
        res = client.get(
            '/api/web/stats',
            cookies={'vetstudy_session': token},
            headers={'X-User-Telegram-Id': '1001'},
        )
        assert res.status_code == 403
    finally:
        settings.web_owner_telegram_id = old_owner_id

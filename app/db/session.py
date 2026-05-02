from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()


def get_engine():
    return create_engine(settings.database_url, pool_pre_ping=True)


SessionLocal = sessionmaker(autocommit=False, autoflush=False)


def new_session():
    SessionLocal.configure(bind=get_engine())
    return SessionLocal()


def get_db():
    db = new_session()
    try:
        yield db
    finally:
        db.close()

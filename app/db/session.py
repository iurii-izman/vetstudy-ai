from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()


def get_engine():
    return create_engine(settings.database_url, pool_pre_ping=True)


ENGINE = get_engine()
SessionLocal = sessionmaker(bind=ENGINE, autocommit=False, autoflush=False)


def new_session():
    return SessionLocal()


def get_db():
    db = new_session()
    try:
        yield db
    finally:
        db.close()

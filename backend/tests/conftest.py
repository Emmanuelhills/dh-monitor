"""Test fixtures.

Integration tests run against a real PostgreSQL database named by DHM_TEST_DATABASE_URL
(read from the environment or backend/.env). It is migrated once per session and truncated
between tests. External services (RDAP/WHOIS, SES, Celery broker) are always mocked.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values

_env = {**dotenv_values(Path(__file__).resolve().parent.parent / ".env"), **os.environ}
TEST_DB_URL = _env.get("DHM_TEST_DATABASE_URL")
if not TEST_DB_URL:
    raise RuntimeError("Set DHM_TEST_DATABASE_URL to a disposable PostgreSQL database for tests.")
os.environ["DHM_DATABASE_URL"] = TEST_DB_URL
os.environ["DHM_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["DHM_LOOKUP_MIN_INTERVAL_SECONDS"] = "0"
os.environ["DHM_ENVIRONMENT"] = "test"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import User  # noqa: E402
from app.services.auth import hash_password  # noqa: E402

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="session", autouse=True)
def _migrated_database():
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def queued_tasks(monkeypatch):
    """Capture Celery .delay() calls instead of talking to a broker."""
    from app.tasks import jobs

    calls: list[tuple[str, tuple]] = []
    for task in (jobs.check_record, jobs.deliver_notification_task):
        monkeypatch.setattr(task, "delay", lambda *args, _name=task.name: calls.append((_name, args)))
    return calls


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def admin_user(db):
    user = User(email=ADMIN_EMAIL, password_hash=hash_password(ADMIN_PASSWORD))
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def anon_client():
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(admin_user):
    """Authenticated client that sends the CSRF header automatically."""
    from app.main import app

    with TestClient(app) as c:
        response = c.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert response.status_code == 200, response.text
        c.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        yield c

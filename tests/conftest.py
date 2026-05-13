import pytest

from app import create_app
from models import User, db as _db, utcnow


@pytest.fixture()
def app():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "MAIL_SUPPRESS_SEND": True,
        "MAIL_DEFAULT_SENDER": "test@example.com",
        "SECRET_KEY": "test-secret-key",
    })
    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_user(app):
    user = User(
        name="Admin",
        email="admin@example.com",
        is_admin=True,
        email_verified_at=utcnow(),
    )
    user.set_password("adminpass123")
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture()
def regular_user(app):
    user = User(
        name="Regular",
        email="user@example.com",
        is_admin=False,
        email_verified_at=utcnow(),
    )
    user.set_password("userpass123")
    _db.session.add(user)
    _db.session.commit()
    return user


@pytest.fixture()
def unverified_user(app):
    user = User(
        name="Unverified",
        email="unverified@example.com",
        is_admin=False,
        email_verified_at=None,
    )
    user.set_password("unverifiedpass123")
    _db.session.add(user)
    _db.session.commit()
    return user

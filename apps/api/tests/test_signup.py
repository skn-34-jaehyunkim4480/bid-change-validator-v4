"""회원가입. 만든 계정은 테스트가 끝나면 지운다."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from apps.api.app.auth_models import AppUser, AuthSession
from apps.api.app.config import get_settings
from apps.api.app.database import SessionLocal
from apps.api.app.main import app


@pytest.fixture
def username():
    name = f"signup-{uuid.uuid4().hex[:10]}"
    yield name
    with SessionLocal() as db:
        user = db.scalar(select(AppUser).where(AppUser.username == name))
        if user is not None:
            db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
            db.delete(user)
            db.commit()


def test_signup_creates_a_free_user_without_company_and_signs_in(username) -> None:
    client = TestClient(app)
    response = client.post("/api/v1/auth/signup", json={"username": f"  {username.upper()} ", "password": "good-pass-42"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["username"] == username  # 앞뒤 공백을 빼고 소문자로
    assert body["user"]["role"] == "USER" and body["user"]["company_id"] is None
    assert "HttpOnly" in response.headers["set-cookie"]
    assert client.get("/api/v1/auth/me").json()["username"] == username  # 바로 로그인된다
    with SessionLocal() as db:
        user = db.scalar(select(AppUser).where(AppUser.username == username))
        assert user.membership_plan == "FREE" and user.password_hash != "good-pass-42"


def test_signup_rejects_a_taken_username(username) -> None:
    client = TestClient(app)
    assert client.post("/api/v1/auth/signup", json={"username": username, "password": "good-pass-42"}).status_code == 201
    again = TestClient(app).post("/api/v1/auth/signup", json={"username": username, "password": "other-pass-77"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "USERNAME_ALREADY_EXISTS"


@pytest.mark.parametrize("payload", [
    {"username": "ab", "password": "good-pass-42"},                  # 아이디가 짧다
    {"username": "한글아이디", "password": "good-pass-42"},            # 허용하지 않는 글자
    {"username": "-dash-first", "password": "good-pass-42"},         # 기호로 시작
    {"username": "valid-name", "password": "short"},                 # 비밀번호가 짧다
    {"username": "valid-name", "password": "Valid-Name"},            # 아이디와 같은 비밀번호
    {"username": "valid-name", "password": "aaaaaaaaaa"},            # 같은 글자만
])
def test_signup_rejects_weak_input(payload) -> None:
    response = TestClient(app).post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(AppUser).where(AppUser.username == payload["username"].casefold())) is None


def test_signup_can_be_turned_off(monkeypatch, username) -> None:
    monkeypatch.setattr(get_settings(), "auth_signup_enabled", False)
    response = TestClient(app).post("/api/v1/auth/signup", json={"username": username, "password": "good-pass-42"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SIGNUP_DISABLED"

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from xxvi.auth.passwords import hash_password
from xxvi.main import create_app, seed_accounts
from xxvi.settings import Settings, get_settings

# A date that is always in the future, however long after 2026 this suite is
# run. The literal this replaced ("2026-08-20", the real go-live) silently
# became the past on 20 Aug 2026 and took
# test_session_reports_the_countdown_before_go_live down with it -- the test
# asserts the run is NOT yet live, which stopped being true of a fixed past
# date. Anything that must be "before go-live" derives it from now.
FAR_FUTURE_ISO = (datetime.now(UTC) + timedelta(days=3650)).isoformat()


@pytest.fixture
def settings():
    return Settings(
        player_username="him",
        player_password_hash=hash_password("pw-him"),
        operator_username="me",
        operator_password_hash=hash_password("pw-me"),
        go_live_iso=FAR_FUTURE_ISO,
    )


@pytest.fixture
async def client(sessionmaker, settings):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.sessionmaker = sessionmaker
    await seed_accounts(sessionmaker, settings)
    transport = ASGITransport(app=app)
    # https, not http: the login cookie is Secure, and httpx's cookie jar
    # (correctly) refuses to resend a Secure cookie over a plain-http
    # base_url on the next request in the same client -- which would make
    # every "log in, then check the session" test in this file look like a
    # session bug when it is actually a scheme mismatch in the test harness.
    async with AsyncClient(transport=transport, base_url="https://test") as c:
        yield c


async def test_anonymous_session_reports_unauthenticated(client):
    response = await client.get("/api/session")
    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert response.json()["role"] is None


async def test_login_with_correct_credentials_sets_a_session(client):
    response = await client.post("/api/auth/login", json={"username": "him", "password": "pw-him"})
    assert response.status_code == 200
    assert response.json()["role"] == "player"

    session = await client.get("/api/session")
    assert session.json()["authenticated"] is True
    assert session.json()["role"] == "player"


async def test_login_with_a_wrong_password_is_rejected(client):
    response = await client.post("/api/auth/login", json={"username": "him", "password": "nope"})
    assert response.status_code == 401


async def test_login_with_an_unknown_user_is_rejected(client):
    response = await client.post("/api/auth/login", json={"username": "ghost", "password": "pw-him"})
    assert response.status_code == 401


async def test_operator_logs_in_with_the_operator_role(client):
    response = await client.post("/api/auth/login", json={"username": "me", "password": "pw-me"})
    assert response.json()["role"] == "operator"


async def test_session_reports_the_countdown_before_go_live(client):
    body = (await client.get("/api/session")).json()
    assert body["live"] is False
    assert body["seconds_until_live"] > 0


async def test_logout_clears_the_session(client):
    await client.post("/api/auth/login", json={"username": "him", "password": "pw-him"})
    await client.post("/api/auth/logout")
    assert (await client.get("/api/session")).json()["authenticated"] is False

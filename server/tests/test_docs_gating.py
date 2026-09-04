"""GET /api/docs and /api/openapi.json must never be readable before an
operator has signed in. The coming-soon page is the only thing an
anonymous visitor is meant to see, with no hint of the structure behind
it -- FastAPI's built-in docs are public by default and, until gated,
hand out all fifteen paths and the Difficulty enum to anyone who asks.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from xxvi.auth.passwords import hash_password
from xxvi.main import create_app, seed_accounts
from xxvi.settings import Settings, get_settings


@pytest.fixture
def settings():
    return Settings(
        player_username="him", player_password_hash=hash_password("pw"),
        operator_username="me", operator_password_hash=hash_password("pw"),
    )


@pytest.fixture
async def app(sessionmaker, settings):
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.state.sessionmaker = sessionmaker
    await seed_accounts(sessionmaker, settings)
    return application


async def test_anonymous_cannot_read_the_openapi_schema(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        response = await c.get("/api/openapi.json")
    assert response.status_code == 401


async def test_anonymous_cannot_read_the_docs_page(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        response = await c.get("/api/docs")
    assert response.status_code == 401


async def test_a_player_cannot_read_the_openapi_schema(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
        response = await c.get("/api/openapi.json")
    assert response.status_code == 403


async def test_an_operator_can_read_the_openapi_schema(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        await c.post("/api/auth/login", json={"username": "me", "password": "pw"})
        response = await c.get("/api/openapi.json")
    assert response.status_code == 200
    body = response.json()
    assert "/api/run" in body["paths"]


async def test_an_operator_can_read_the_docs_page(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        await c.post("/api/auth/login", json={"username": "me", "password": "pw"})
        response = await c.get("/api/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()

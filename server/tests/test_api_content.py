import pytest
from httpx import ASGITransport, AsyncClient

from xxvi.auth.passwords import hash_password
from xxvi.content.loader import load_config
from xxvi.main import create_app, seed_accounts
from xxvi.settings import Settings, get_settings
from tests.paths import EXAMPLE_CONFIG

CODE = "ABCD-EFGH-IJKL"


def _settings(**overrides) -> Settings:
    base = dict(
        player_username="him", player_password_hash=hash_password("pw"),
        operator_username="me", operator_password_hash=hash_password("pw"),
        activation_code_hash=hash_password(CODE),
        checkpoint_1_hash=hash_password(CODE),
        checkpoint_2_hash=hash_password(CODE),
    )
    base.update(overrides)
    return Settings(**base)


async def _make_client(sessionmaker, settings: Settings, *, login: tuple[str, str] | None) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.sessionmaker = sessionmaker
    app.state.config = load_config(EXAMPLE_CONFIG)
    await seed_accounts(sessionmaker, settings)
    # https, not http -- see test_api_auth.py: the login cookie is Secure
    # and httpx's jar drops it on the next request over plain http. Not
    # entered as `async with` here -- login (if any) already sends a
    # request, which lazily opens the client; entering the context manager
    # a second time in a fixture would raise "Cannot open ... more than
    # once". Callers close it explicitly instead (see fixtures below).
    c = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    if login is not None:
        username, password = login
        await c.post("/api/auth/login", json={"username": username, "password": password})
    return c


@pytest.fixture
async def client(sessionmaker):
    # No login at all -- exactly the anonymous caller App.tsx's coming-soon
    # page (and a bare curl) is. `go_live_iso` is left at its future
    # default; this tier must be restricted whether or not the run is live.
    c = await _make_client(sessionmaker, _settings(), login=None)
    try:
        yield c
    finally:
        await c.aclose()


@pytest.fixture
async def prelive_player_client(sessionmaker):
    c = await _make_client(
        sessionmaker,
        _settings(go_live_iso="2099-01-01T00:00:00+05:30"),  # not live
        login=("him", "pw"),
    )
    try:
        yield c
    finally:
        await c.aclose()


@pytest.fixture
async def live_player_client(sessionmaker):
    c = await _make_client(
        sessionmaker,
        _settings(go_live_iso="2020-01-01T00:00:00+05:30"),  # already live
        login=("him", "pw"),
    )
    try:
        yield c
    finally:
        await c.aclose()


@pytest.fixture
async def prelive_operator_client(sessionmaker):
    # The operator's own dashboard needs the real content regardless of the
    # gate (mirrors require_live's operator carve-out) -- not live here on
    # purpose, to prove that tier is what actually grants the full payload,
    # not merely "logged in".
    c = await _make_client(
        sessionmaker,
        _settings(go_live_iso="2099-01-01T00:00:00+05:30"),  # not live
        login=("me", "pw"),
    )
    try:
        yield c
    finally:
        await c.aclose()


async def test_content_is_readable_without_signing_in(client):
    assert (await client.get("/api/content")).status_code == 200


async def test_anonymous_response_has_no_trophy_names_and_no_closing_message(client):
    # Ship-blocking finding, reproduced end to end (task-30 review):
    # /api/content had no require_live and no session requirement. A real
    # anonymous pre-go-live request got 200 back with all 19 standard
    # trophy names, how_to_play, teaser, and the closing message -- only
    # hidden trophies were ever masked. One curl handed over the entire
    # emotional payoff of the night. Only coming_soon is meant to be public.
    body = (await client.get("/api/content")).json()
    assert body["trophies"] == []
    assert body["copy"]["closing"] == ""
    assert body["copy"]["how_to_play"] == ""
    assert body["copy"]["teaser"] == ""
    assert body["copy"]["coming_soon"] != ""
    assert "questions" not in body


async def test_anonymous_response_is_restricted_even_once_the_run_is_live(sessionmaker):
    # The restriction is about WHO is asking (no session), not WHEN --
    # an anonymous caller must not get the full payload just because
    # midnight has already passed for someone else's run.
    c = await _make_client(
        sessionmaker, _settings(go_live_iso="2020-01-01T00:00:00+05:30"), login=None
    )
    async with c:
        body = (await c.get("/api/content")).json()
    assert body["trophies"] == []
    assert body["copy"]["closing"] == ""


async def test_authenticated_player_before_go_live_gets_the_teaser_but_nothing_else(
    prelive_player_client,
):
    # App.tsx's ComingSoon personalises with `teaser` for an authenticated
    # player before go-live (see App.tsx's `personalised` branch) -- that
    # established, already-shipped behaviour must survive this fix. Trophy
    # names, how_to_play, and the closing message are still the payoff of a
    # run he hasn't started, so they stay withheld at this tier.
    body = (await prelive_player_client.get("/api/content")).json()
    assert body["copy"]["teaser"] != ""
    assert body["trophies"] == []
    assert body["copy"]["closing"] == ""
    assert body["copy"]["how_to_play"] == ""


async def test_operator_gets_the_full_payload_even_before_go_live(prelive_operator_client):
    # The operator dashboard needs the real content regardless of the gate.
    body = (await prelive_operator_client.get("/api/content")).json()
    assert body["trophies"] != []
    assert body["copy"]["closing"] != ""
    assert body["copy"]["how_to_play"] != ""


async def test_hidden_trophy_names_are_masked_server_side(live_player_client):
    body = (await live_player_client.get("/api/content")).json()
    hidden = [t for t in body["trophies"] if t["hidden"]]
    assert hidden, "the example config defines hidden trophies"
    assert all(t["name"] == "???" for t in hidden)


async def test_a_real_hidden_trophy_name_is_masked_not_just_a_placeholder_one(
    sessionmaker,
):
    # The example config's hidden trophies already use "???" as their own
    # placeholder *content*, so the test above can't actually tell "masked"
    # apart from "never masked, config just happened to say ???" -- a
    # masking bug there would still show `name == "???"` and the test would
    # pass either way. Build a config with a REAL hidden name and confirm
    # the endpoint replaces it, not just happens to match it.
    config = load_config(EXAMPLE_CONFIG)
    trophies = [
        t.model_copy(update={"name": "The Midnight Rage Quit"})
        if t.id == "hidden-rage-quit" else t
        for t in config.trophies
    ]
    real_config = config.model_copy(update={"trophies": trophies})

    settings = _settings(go_live_iso="2020-01-01T00:00:00+05:30")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.sessionmaker = sessionmaker
    app.state.config = real_config
    await seed_accounts(sessionmaker, settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
        body = (await c.get("/api/content")).json()
    trophy = next(t for t in body["trophies"] if t["id"] == "hidden-rage-quit")
    assert trophy["hidden"] is True
    assert trophy["name"] == "???"
    assert trophy["name"] != "The Midnight Rage Quit"


async def test_standard_trophy_names_are_present(live_player_client):
    body = (await live_player_client.get("/api/content")).json()
    platinum = next(t for t in body["trophies"] if t["id"] == "platinum")
    assert platinum["name"] != "???"


async def test_question_text_is_not_served_by_the_content_endpoint(live_player_client):
    raw = (await live_player_client.get("/api/content")).text
    assert "placeholder" not in raw.lower() or "roast" not in raw.lower()
    body = (await live_player_client.get("/api/content")).json()
    assert "questions" not in body

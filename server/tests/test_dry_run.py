from httpx import ASGITransport, AsyncClient

from xxvi.auth.passwords import hash_password
from xxvi.core.models import Difficulty
from xxvi.main import create_app, seed_accounts
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings, get_settings
from xxvi.vault.service import VaultService

REAL = "REAL-CODE-NEVER-IN-A-REHEARSAL"


async def test_dry_run_release_never_returns_the_real_code(sessionmaker, account):
    run = await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)
    vault = VaultService(sessionmaker, Settings(reward_1_code=REAL, dry_run=True))
    code = await vault.release(run.id, 1, approved_by_operator=True)
    assert code != REAL
    assert code.startswith("DRY-RUN")


async def test_a_dry_run_release_leaves_no_trace_that_blocks_the_real_one(sessionmaker, account):
    # CRITICAL, reproduced end to end by the operator-surface review: a
    # rehearsal used to commit a real CodeRelease row, permanently consuming
    # (run_id, reward_id) -- so a forgotten rehearsal made the REAL release
    # 409 forever, at exit code 0. Any number of dry runs must still let the
    # real release through afterwards, and it must yield the real code.
    run = await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)

    dry_vault = VaultService(sessionmaker, Settings(reward_1_code=REAL, dry_run=True))
    for _ in range(3):
        dry_code = await dry_vault.release(run.id, 1, approved_by_operator=True)
        assert dry_code != REAL

    # Nothing was persisted by any of the dry runs.
    assert await dry_vault.released_reward_ids(run.id) == frozenset()

    real_vault = VaultService(sessionmaker, Settings(reward_1_code=REAL, dry_run=False))
    real_code = await real_vault.release(run.id, 1, approved_by_operator=True)
    assert real_code == REAL
    assert await real_vault.released_reward_ids(run.id) == frozenset({1})


async def test_dry_run_lets_the_operator_in_before_go_live(sessionmaker):
    # `!= 423` is not enough here: `require_live`'s dry-run bypass gets the
    # operator past the go-live gate, but every player route ALSO carries
    # `require_player` -- and until that admits the operator too under
    # dry_run, he gets 403 on all ten player routes. `403 != 423` is true,
    # so a test asserting only `!= 423` (as an earlier version of this test
    # did) passes even though the rehearsal is completely inert. This
    # asserts the real thing: 200, not merely "not specifically 423".
    settings = Settings(
        operator_username="me", operator_password_hash=hash_password("pw"),
        player_username="him", player_password_hash=hash_password("pw"),
        activation_code_hash=hash_password("CODE"),
        go_live_iso="2030-01-01T00:00:00+05:30", dry_run=True,
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.sessionmaker = sessionmaker
    await seed_accounts(sessionmaker, settings)

    # https, not http -- see test_api_auth.py: the login cookie is Secure
    # and would otherwise be silently dropped by httpx's cookie jar on the
    # next request, which would masquerade as an auth/dry-run bug.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        await c.post("/api/auth/login", json={"username": "me", "password": "pw"})
        assert (await c.get("/api/run")).status_code == 200

        # The rehearsal is the FULL player experience, not just a read --
        # the operator must be able to actually play through it, not merely
        # see a read-only view.
        activate = await c.post("/api/run/activate", json={"code": "CODE"})
        assert activate.status_code == 200
        assert activate.json()["phase"] == "profile"

        await c.post("/api/auth/logout")
        await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
        # Dry run is for the operator only. He still waits for midnight.
        assert (await c.get("/api/run")).status_code == 423


async def test_outside_dry_run_an_operator_still_cannot_reach_player_routes(sessionmaker):
    # Pins the role check itself: without dry_run, require_player's
    # rejection of a non-player session is the only thing standing between
    # an operator account and every player route. Removing that check
    # entirely (I3/M16) passed the full suite before this test existed --
    # nothing exercised an operator hitting a player route outside dry_run.
    settings = Settings(
        operator_username="me", operator_password_hash=hash_password("pw"),
        player_username="him", player_password_hash=hash_password("pw"),
        go_live_iso="2020-01-01T00:00:00+05:30", dry_run=False,
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.sessionmaker = sessionmaker
    await seed_accounts(sessionmaker, settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        await c.post("/api/auth/login", json={"username": "me", "password": "pw"})
        assert (await c.get("/api/run")).status_code == 403
        assert (await c.post("/api/run/activate", json={"code": "X"})).status_code == 403

from configparser import ConfigParser
from pathlib import Path

import pytest

from xxvi.auth.passwords import hash_password
from xxvi.settings import (
    ConfigNotProductionReady,
    Settings,
    escape_percent_for_configparser,
    get_settings,
)

SERVER_DIR = Path(__file__).resolve().parents[1]


def _production_ready_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://neondb_owner:x@ep-real.neon.tech/neondb",
        reward_1_code="REAL-0001", reward_2_code="REAL-0002",
        session_secret="a-genuinely-random-secret-not-the-dev-default-x7q2",
        player_password_hash=hash_password("pw"),
        operator_password_hash=hash_password("pw"),
        activation_code_hash=hash_password("ACTIVATE"),
        checkpoint_1_hash=hash_password("CHECK1"),
        checkpoint_2_hash=hash_password("CHECK2"),
    )


# --- Settings.assert_production_ready(). Deliberately NOT wired into
# get_settings() itself -- see the method's own docstring -- so these test
# the method directly rather than through get_settings().


def test_assert_production_ready_passes_with_full_production_config():
    _production_ready_settings().assert_production_ready()  # must not raise


def test_assert_production_ready_rejects_a_dummy_reward_code():
    settings = _production_ready_settings().model_copy(
        update={"reward_1_code": "DUMMY-REWARD-0001"}
    )
    with pytest.raises(ConfigNotProductionReady, match="reward_1_code"):
        settings.assert_production_ready()


def test_assert_production_ready_rejects_the_dev_session_secret():
    settings = _production_ready_settings().model_copy(
        update={"session_secret": "dev-only-not-a-real-secret"}
    )
    with pytest.raises(ConfigNotProductionReady, match="session_secret"):
        settings.assert_production_ready()


def test_assert_production_ready_rejects_an_empty_password_hash():
    settings = _production_ready_settings().model_copy(update={"player_password_hash": ""})
    with pytest.raises(ConfigNotProductionReady, match="player_password_hash"):
        settings.assert_production_ready()


def test_assert_production_ready_rejects_empty_gate_hashes():
    for field in ("activation_code_hash", "checkpoint_1_hash", "checkpoint_2_hash"):
        settings = _production_ready_settings().model_copy(update={field: ""})
        with pytest.raises(ConfigNotProductionReady, match=field):
            settings.assert_production_ready()


def test_assert_production_ready_rejects_dry_run():
    # CRITICAL: a dry run must never be allowed down the real release path.
    # Reproduced end to end before this fix: DRY_RUN=true check-config said
    # "config OK", and DRY_RUN=true release printed a DRY-RUN- code with
    # exit 0 -- looking like a real release succeeded.
    settings = _production_ready_settings().model_copy(update={"dry_run": True})
    with pytest.raises(ConfigNotProductionReady, match="dry_run"):
        settings.assert_production_ready()


def test_assert_production_ready_rejects_an_empty_reward_code():
    settings = _production_ready_settings().model_copy(update={"reward_1_code": ""})
    with pytest.raises(ConfigNotProductionReady, match="reward_1_code"):
        settings.assert_production_ready()


def test_assert_production_ready_rejects_the_default_database_url():
    # MINOR: database_url was entirely unchecked despite the docstring
    # naming "wrong database" as one of the three Criticals this method
    # exists to prevent.
    settings = _production_ready_settings().model_copy(
        update={"database_url": "postgresql+asyncpg://localhost/xxvi"}
    )
    with pytest.raises(ConfigNotProductionReady, match="database_url"):
        settings.assert_production_ready()


def test_assert_production_ready_rejects_the_env_files_actual_dev_secret():
    # The repo's own .env ships SESSION_SECRET=dev-only-rotate-before-the-20th
    # -- a DIFFERENT string from the exact literal the old check compared
    # against, so it evaded that check entirely. This is the real value
    # from that file, not the placeholder default.
    settings = _production_ready_settings().model_copy(
        update={"session_secret": "dev-only-rotate-before-the-20th"}
    )
    with pytest.raises(ConfigNotProductionReady, match="session_secret"):
        settings.assert_production_ready()


def test_assert_production_ready_rejects_a_short_low_entropy_secret_without_dev_prefix():
    # Generalised beyond the "dev-" prefix signal too: a short, low-entropy,
    # human-typed-looking secret should be caught even without that prefix.
    settings = _production_ready_settings().model_copy(
        update={"session_secret": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
    )
    with pytest.raises(ConfigNotProductionReady, match="session_secret"):
        settings.assert_production_ready()


def test_assert_production_ready_accepts_a_long_high_entropy_generated_secret():
    import secrets

    settings = _production_ready_settings().model_copy(
        update={"session_secret": secrets.token_urlsafe(32)}
    )
    settings.assert_production_ready()  # must not raise


def test_assert_production_ready_names_every_offender_at_once():
    # Under time pressure at midnight, a fix-rerun-fail loop that reports one
    # offender per attempt is worse than one message naming all of them.
    settings = Settings()  # every field at its insecure/dummy default
    with pytest.raises(ConfigNotProductionReady) as exc:
        settings.assert_production_ready()
    message = str(exc.value)
    for expected in (
        "reward_1_code", "reward_2_code", "session_secret",
        "player_password_hash", "operator_password_hash",
        "activation_code_hash", "checkpoint_1_hash", "checkpoint_2_hash",
    ):
        assert expected in message, f"{expected!r} missing from: {message}"


def test_get_settings_never_calls_assert_production_ready(monkeypatch):
    # get_settings() is used pervasively, including by every test in this
    # suite with intentionally-partial config -- it must never itself raise
    # ConfigNotProductionReady, or all of that breaks.
    get_settings.cache_clear()
    called = False

    original = Settings.assert_production_ready

    def _tripwire(self):
        nonlocal called
        called = True
        return original(self)

    monkeypatch.setattr(Settings, "assert_production_ready", _tripwire)
    get_settings()  # dummy config by default; must not raise, must not call it
    assert called is False
    get_settings.cache_clear()


def test_escape_percent_doubles_every_percent_sign():
    assert escape_percent_for_configparser("no-percent-here") == "no-percent-here"
    assert (
        escape_percent_for_configparser("postgresql+asyncpg://u:p%40ss@host/db")
        == "postgresql+asyncpg://u:p%%40ss@host/db"
    )


def test_escaped_url_survives_real_configparser_interpolation():
    # This is the exact failure mode: alembic's `config.set_main_option` routes
    # through ConfigParser's basic interpolation, which raises on a bare `%`
    # that isn't followed by `%` or a `(name)s` reference — e.g. a Neon URL
    # with a percent-encoded character in the password. Deploy day runs this
    # once and it cannot be patched, so this is proven against the real
    # ConfigParser, not just string equality.
    raw_url = "postgresql+asyncpg://user:p%40ssw0rd@ep-something.neon.tech/xxvi"

    parser = ConfigParser()
    parser.add_section("alembic")

    # Unescaped: reproduces the crash this fix prevents.
    try:
        parser.set("alembic", "sqlalchemy.url", raw_url)
        parser.get("alembic", "sqlalchemy.url")
        crashed_without_escaping = False
    except ValueError:
        crashed_without_escaping = True
    assert crashed_without_escaping, "expected raw %-containing URL to break ConfigParser"

    # Escaped: must round-trip back to the original URL.
    parser.set("alembic", "sqlalchemy.url", escape_percent_for_configparser(raw_url))
    assert parser.get("alembic", "sqlalchemy.url") == raw_url


# --- env_file resolution. `.env` lives at the repo root; every documented
# command runs from `server/`. A bare `env_file=".env"` resolves against CWD
# and silently finds nothing from `server/`, falling back to every default
# with no error -- wrong database, dummy reward codes, empty password hashes.
# These pin the ancestor-walk fix at both the helper level and through the
# real `get_settings()` entrypoint, against the real repo-root `.env`.


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_resolve_env_file_prefers_a_cwd_relative_env_over_walking_up(tmp_path, monkeypatch):
    # Docker supplies `.env` directly in the working directory. That must be
    # found without walking anywhere -- confirms the CWD-relative check runs
    # (and is checked) before the ancestor walk.
    from xxvi.settings import _resolve_env_file

    (tmp_path / ".env").write_text("FOO=bar\n")
    monkeypatch.chdir(tmp_path)

    assert _resolve_env_file() == ".env"


def test_the_ancestor_walk_finds_a_repo_root_env_from_the_server_directory(tmp_path):
    """The documented dev workflow: CWD is `server/`, `.env` is one dir up.

    Built as a synthetic repo rather than run against this one. The previous
    version asserted `_resolve_env_file()` resolved to the REAL repo's
    `.env` -- a gitignored file that exists only on a machine where someone
    has set one up. It passed for the author and failed in CI and on every
    fresh clone, because `_resolve_env_file` anchors its walk at settings.py
    and falls back to the bare filename when nothing is found. Same class of
    bug as the wall-clock go-live test: green locally, red for everyone else.

    `find_upwards` is the mechanism under test, and it takes an explicit
    anchor, so it can be pointed at a tree this test fully controls -- the
    same approach the "nothing found anywhere" test below already uses.
    """
    from xxvi.pathutils import find_upwards

    (tmp_path / ".git").mkdir()          # the repo-root sentinel
    (tmp_path / ".env").write_text("DATABASE_URL=postgresql+asyncpg://example/db\n")
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    assert not (server_dir / ".env").exists(), "the walk must be what finds it"

    found = find_upwards(".env", server_dir)
    assert found is not None
    assert found.resolve() == (tmp_path / ".env").resolve()


def test_resolve_env_file_falls_back_to_bare_filename_when_nothing_is_found(tmp_path, monkeypatch):
    # `_resolve_env_file`'s anchor is settings.py's own location, which is
    # always inside this repo (real .env always found from there) -- so the
    # "nothing found anywhere" case is exercised at the reusable helper
    # (`find_upwards`) with an isolated anchor instead. Must return None
    # rather than raise: a missing .env is a valid state (e.g. CI), and
    # `_resolve_env_file` turns that None into the original bare-filename
    # fallback, preserving the pre-fix silent-default behaviour.
    from xxvi.pathutils import find_upwards

    isolated = tmp_path / "a" / "b" / "c"
    isolated.mkdir(parents=True)

    assert find_upwards(".env", isolated) is None


def test_get_settings_reads_an_env_file_instead_of_silently_using_defaults(tmp_path, monkeypatch):
    """Confirmed-live regression: `get_settings().database_url` used to
    return the class default while a fully populated `.env` sat unread.

    Driven through the real entrypoint, but against an `.env` this test
    writes itself. It used to rely on the author's own gitignored `.env`
    being present, so on a clean checkout there was no `.env` anywhere,
    `database_url` WAS the default, and the assertion inverted -- green
    locally, red in CI.
    """
    get_settings.cache_clear()
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql+asyncpg://user:pw@example.invalid/somedb\n"
    )

    settings = get_settings()
    get_settings.cache_clear()

    default_database_url = Settings.model_fields["database_url"].default
    assert settings.database_url != default_database_url
    # Deliberately NOT asserting a provider hostname. This used to check for
    # "neon.tech", which made the test a statement about where the database
    # happens to be hosted rather than about `.env` being found at all --
    # moving to a local Postgres broke it while the behaviour it exists to
    # protect was completely unaffected.
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_real_env_var_still_wins_over_the_env_file(monkeypatch):
    # Docker supplies config via real environment variables. That must keep
    # overriding the file, even now that the file actually resolves.
    monkeypatch.chdir(SERVER_DIR)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://env-var-wins/xxvi")

    settings = get_settings()

    assert settings.database_url == "postgresql+asyncpg://env-var-wins/xxvi"


def test_a_realistic_looking_rehearsal_code_is_still_refused():
    """The rehearsal codes look exactly like real PSN cards -- that realism is
    deliberate, and it is exactly why the guard must know them by value.

    Without this, the operator could rehearse, forget to swap the codes, and
    have `cli release` print a plausible code at midnight that redeems as
    nothing. `DUMMY-REWARD-0001` announces itself; `2LV9-C7AZ-JPSK` does not.
    """
    from xxvi.settings import ConfigNotProductionReady, Settings

    settings = _production_ready_settings()
    settings.reward_1_code = "2LV9-C7AZ-JPSK"
    settings.reward_2_code = "5NPA-BPNC-75YX"
    with pytest.raises(ConfigNotProductionReady) as excinfo:
        settings.assert_production_ready()
    message = str(excinfo.value)
    assert "reward_1_code" in message
    assert "reward_2_code" in message
    # The code itself must never appear in the refusal -- these are shaped like
    # real cards and this message is printed to a terminal and read aloud.
    assert "2LV9-C7AZ-JPSK" not in message


def test_a_genuine_looking_code_that_is_not_a_rehearsal_code_passes():
    settings = _production_ready_settings()
    settings.reward_1_code = "9XQM-4TRB-KD73"
    settings.reward_2_code = "PW82-JHNC-6VZY"
    settings.assert_production_ready()

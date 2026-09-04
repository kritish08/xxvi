import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from xxvi.pathutils import find_upwards

_ENV_FILENAME = ".env"

_DUMMY_REWARD_PREFIX = "DUMMY-REWARD-"

# Rehearsal codes are deliberately shaped like real PSN gift cards, so the dress
# rehearsal looks and reads exactly like the night itself. That realism is the
# whole point -- and it is also precisely why they must be enumerated here.
# `DUMMY-REWARD-0001` announces itself; `2LV9-C7AZ-JPSK` does not, so without
# this list the operator could run a rehearsal, forget to swap the values, and
# have `cli release` print a plausible-looking code at midnight that redeems as
# nothing. That is the exact failure `assert_production_ready` exists to prevent.
# Any code minted for testing belongs in here the moment it is minted.
_REHEARSAL_REWARD_CODES = frozenset({
    "2LV9-C7AZ-JPSK",
    "5NPA-BPNC-75YX",
})


def _is_placeholder_reward(code: str) -> bool:
    """True for anything that is not a real gift card, however real it looks."""
    return (
        not code
        or code.startswith(_DUMMY_REWARD_PREFIX)
        or code.strip().upper() in _REHEARSAL_REWARD_CODES
    )


# Mirrors `Settings.database_url`'s own class default below, so
# `assert_production_ready` can catch "config silently resolved to its
# localhost default" without hardcoding the string twice.
_DEFAULT_DATABASE_URL = "postgresql+asyncpg://localhost/xxvi"

# A real session secret should be a long, randomly generated token (e.g.
# `secrets.token_urlsafe(32)`), not a human-typed reminder phrase. A
# floor on length and on distinct-character count catches that shape
# generally, rather than only the one exact string this file used to
# hardcode -- see `_looks_like_a_dev_secret`'s docstring.
_MIN_SESSION_SECRET_LENGTH = 32
_MIN_SESSION_SECRET_DISTINCT_CHARS = 12


def _looks_like_a_dev_secret(secret: str) -> bool:
    """Catch obviously-non-production session secrets in general, not just
    an exact match on one placeholder string.

    The exact-match check this replaced compared `session_secret` against
    the literal `"dev-only-not-a-real-secret"` default -- and the repo's
    own `.env` ships `SESSION_SECRET=dev-only-rotate-before-the-20th`,
    a *different* human-typed reminder that sailed straight through it.
    Three independent signals catch that shape of string generally instead
    of chasing exact strings one at a time:

    - a `dev-` prefix (case-insensitive) -- the actual pattern both known
      offenders share, and the cheapest tell that someone typed a
      reminder-to-self rather than generating a secret.
    - too short -- a secret used to sign session cookies should be at
      least `_MIN_SESSION_SECRET_LENGTH` long; both known offenders are
      well under it.
    - too little entropy for a secret of its length -- a human-typed
      phrase built from a small alphabet of lowercase letters, digits and
      hyphens has far fewer distinct characters than a real generated
      token does at the same length.

    Any one signal alone has false positives/negatives (a legitimately
    generated secret could in principle start with "dev-" by chance, or a
    short-but-random secret could exist); a secret tripping any of them is
    still treated as non-production, since the cost of a false positive
    here (rerun the generator) is trivial next to the cost of a false
    negative (a real release signed with a guessable secret).
    """
    if secret.lower().startswith("dev-"):
        return True
    if len(secret) < _MIN_SESSION_SECRET_LENGTH:
        return True
    if len(set(secret)) < _MIN_SESSION_SECRET_DISTINCT_CHARS:
        return True
    return False


class ConfigNotProductionReady(Exception):
    """Raised by `Settings.assert_production_ready()`. See its docstring."""


def _resolve_env_file() -> str:
    """Resolve `.env` the same way `content/loader.py` resolves `config_path`.

    `.env` lives at the repo root; every documented command runs from
    `server/`. A bare `env_file=".env"` on `model_config` resolves against
    the process CWD, so it silently finds nothing when run from `server/`
    and every setting falls back to its (insecure/dummy) default with no
    error -- wrong database, dummy reward codes, empty password hashes.

    Resolution order:
    1. CWD-relative `.env` (covers Docker, where WORKDIR holds `.env` directly).
    2. An ancestor walk up from this file's directory (covers the documented
       dev workflow, `.env` one directory above `server/`).
    3. The bare filename, unchanged -- if nothing is found, this preserves
       the original (silent-fallback-to-defaults) behaviour rather than
       raising, since a missing `.env` is a valid state (e.g. CI).
    """
    cwd_relative = Path(_ENV_FILENAME)
    if cwd_relative.exists():
        return str(cwd_relative)

    found = find_upwards(_ENV_FILENAME, Path(__file__).resolve().parent)
    return str(found) if found is not None else _ENV_FILENAME


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILENAME, extra="ignore")

    config_path: str = "config/run.yaml"
    database_url: str = "postgresql+asyncpg://localhost/xxvi"
    session_secret: str = "dev-only-not-a-real-secret"

    # Gate secrets are stored hashed. Plaintext never lives in config.
    activation_code_hash: str = ""
    checkpoint_1_hash: str = ""
    checkpoint_2_hash: str = ""

    # Gift card codes. Never logged, never persisted, never serialised
    # except at the moment of an operator-approved release.
    reward_1_code: str = "DUMMY-REWARD-0001"
    reward_2_code: str = "DUMMY-REWARD-0002"

    player_username: str = "player"
    player_password_hash: str = ""
    operator_username: str = "operator"
    operator_password_hash: str = ""

    go_live_iso: str = "2026-08-20T00:00:00+05:30"
    dry_run: bool = False

    def checkpoint_hash(self, act: int) -> str:
        """The argon2 hash of act N's checkpoint code.

        Acts 1 and 2 keep their declared fields so every existing `.env` and
        every test that constructs `Settings(checkpoint_1_hash=...)` keeps
        working untouched. Acts beyond that read `CHECKPOINT_{n}_HASH` from
        the environment directly, because pydantic-settings can only declare
        a fixed set of fields and the whole point here is that the count is
        no longer fixed. A missing hash returns "" -- the same value an
        unset declared field has -- and `assert_production_ready` is what
        turns that into a loud refusal.
        """
        if act == 1:
            return self.checkpoint_1_hash
        if act == 2:
            return self.checkpoint_2_hash
        return os.environ.get(f"CHECKPOINT_{act}_HASH", "")

    def reward_code(self, reward_id: int) -> str:
        """The gift code for reward N, or "" if none is configured.

        Rewards 1 and 2 keep their declared fields so existing `.env` files
        and tests are untouched; beyond that, `REWARD_{n}_CODE` is read from
        the environment. Returning "" for an unconfigured reward is
        deliberate -- `_is_placeholder_reward("")` is already True, so
        `assert_production_ready` refuses it, and `VaultService._code_for`
        turns it into `UnknownReward` rather than emitting a blank code.
        """
        if reward_id == 1:
            return self.reward_1_code
        if reward_id == 2:
            return self.reward_2_code
        return os.environ.get(f"REWARD_{reward_id}_CODE", "")

    def assert_production_ready(self) -> None:
        """Refuse to proceed with dev/placeholder configuration still in place.

        Deliberately NOT called from `get_settings()` itself: that accessor
        is used pervasively -- by every test in this suite, by session
        signing, by code paths that legitimately run with partial config
        (e.g. a fixture that only sets the fields it's testing). Raising
        there would break all of that. This is instead an explicit, opt-in
        gate for the one moment it actually matters: the real release path
        at midnight.

        Three separate Criticals on this project traced back to config
        silently resolving to its (insecure/dummy) defaults with no error --
        wrong database, dummy reward codes, empty password hashes. The worst
        version of that bug is `python -m xxvi.cli release` printing
        `DUMMY-REWARD-0001` and looking like it worked, because that command
        is the fallback used precisely when the dashboard is broken and
        there is no time to debug why a code looks wrong. This enumerates
        every dev/dummy sentinel it knows about and names every offender in
        one exception, rather than failing on the first one and hiding the
        rest behind a fix-rerun-fail loop under time pressure. `database_url`
        is checked here too, against its own class default, so "wrong
        database" is actually one of the things this catches rather than
        just one of the three it's named after.

        The reward-code and checkpoint-hash checks below both walk what
        `config/run.yaml` actually declares (`get_config().rewards` and
        `get_config().acts`) rather than a hardcoded two, so a third reward
        with no `REWARD_3_CODE` set, or a third act with no
        `CHECKPOINT_3_HASH` set, is caught here instead of silently reading
        "" and failing open at the gate itself. `get_config` is imported
        locally, not at module level: `xxvi.content.loader` itself does
        `from xxvi.settings import get_settings`, so a module-level import
        here would close settings -> loader -> settings into a cycle and
        the package would stop importing at all.
        """
        from xxvi.content.loader import get_config

        offenders: list[str] = []
        if self.dry_run:
            offenders.append(
                "dry_run is enabled -- a production release must never run in "
                "dry-run mode"
            )
        for reward in get_config().rewards:
            if _is_placeholder_reward(self.reward_code(reward.id)):
                offenders.append(
                    f"reward_{reward.id}_code is empty, the dummy placeholder, or a "
                    "known rehearsal code -- it is not a real gift card"
                )
        if self.database_url == _DEFAULT_DATABASE_URL:
            offenders.append("database_url is still the localhost default")
        if _looks_like_a_dev_secret(self.session_secret):
            offenders.append("session_secret looks like a dev/placeholder secret")
        if not self.player_password_hash:
            offenders.append("player_password_hash is empty")
        if not self.operator_password_hash:
            offenders.append("operator_password_hash is empty")
        if not self.activation_code_hash:
            offenders.append("activation_code_hash is empty")
        for act in range(1, get_config().acts + 1):
            if not self.checkpoint_hash(act):
                # Named `checkpoint_{act}_hash`, matching the declared
                # field names for acts 1 and 2 exactly (existing tests and
                # tooling grep for those literal substrings), and extending
                # the same shape to any act beyond two.
                offenders.append(f"checkpoint_{act}_hash is empty")
        if offenders:
            raise ConfigNotProductionReady(
                "refusing to proceed with dev/placeholder configuration: "
                + "; ".join(offenders)
            )


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=_resolve_env_file())


def escape_percent_for_configparser(url: str) -> str:
    """Escape literal `%` so alembic's ConfigParser-backed `set_main_option`
    doesn't choke on a `%`-containing value (e.g. a percent-encoded
    character in a Neon connection string's password). `%` is
    ConfigParser's interpolation marker; `%%` is how you spell a literal
    `%` to it. Deploy-day only runs once and cannot be patched, so this is
    applied unconditionally rather than only when a `%` is detected.
    """
    return url.replace("%", "%%")

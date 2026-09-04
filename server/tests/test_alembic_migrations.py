import subprocess
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]

# --- Pins the alembic/env.py CALL SITE, not just the escape helper.
#
# `escape_percent_for_configparser` has its own unit tests in
# test_settings.py, but nothing there proves `alembic/env.py` actually
# *calls* it. Revert env.py's `set_main_option(...)` line to the raw
# `get_settings().database_url` and the whole suite still passes -- the
# helper is correct in isolation, its use is not pinned anywhere.
#
# A Neon password containing a percent-encoded character (entirely
# plausible: Neon generates them) would abort `alembic upgrade head` with a
# ConfigParser interpolation error before a single table exists. Deploy day
# runs this once, live, and cannot be patched after the fact.
#
# `--sql` runs alembic in *offline* mode (see env.py's
# `context.is_offline_mode()` branch): it renders the migration SQL to
# stdout without opening a database connection. That makes this reproducible
# in CI/sandbox with no Postgres reachable, while still exercising the exact
# line (`config.set_main_option`, backed by a real ConfigParser) that fails
# on deploy day.


def test_alembic_upgrade_head_sql_succeeds_with_a_percent_in_database_url():
    percent_bearing_url = (
        "postgresql+asyncpg://neondb_owner:p%40ssw0rd@"
        "ep-example-000000.us-east-2.aws.neon.tech/neondb?ssl=require"
    )

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=SERVER_DIR,
        env={"PATH": "/usr/bin:/bin", "DATABASE_URL": percent_bearing_url},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        "alembic upgrade head --sql failed with a %-containing DATABASE_URL "
        f"(this is the deploy-day failure mode):\n{result.stderr}"
    )
    # Offline mode renders real DDL to stdout; a hollow success (empty
    # output) would be as bad as a crash.
    assert "CREATE TABLE" in result.stdout

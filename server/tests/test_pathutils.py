from xxvi.pathutils import find_upwards
from xxvi.settings import get_settings

# --- The ancestor walk must be bounded at the repository boundary. This
# matters more for `.env` than it ever did for `config_path`: an unbounded
# walk that picks up an unrelated ancestor's file (a stray `~/.env` on a
# shared machine, say) would silently load the wrong secrets -- database
# URL, session secret, reward codes -- the same failure class the env_file
# fix was meant to close, reintroduced in a different shape.
#
# `pyproject.toml` is NOT a sentinel (see pathutils.py's module docstring
# for why): it lives in `server/`, one level below this repo's true root,
# so using it as the fallback landed the boundary one directory too shallow
# in exactly the deploy shape with no `.git` -- silently reintroducing the
# original bug. `.env.example` replaces it: committed, so it travels with
# any clone/tarball/CI artifact, and co-located with `.env` by construction.
#
# The four tests below are the four real deploy shapes, each with a fixture
# that mirrors the actual layout: sentinel candidates at the root,
# `pyproject.toml` one level below it in `server/` wherever it appears at
# all, to prove it is inert.


def test_shape_1_git_checkout_resolves_env_at_the_root(tmp_path):
    # .git and .env at the true root; pyproject.toml one level below, in
    # server/ -- must not stop the walk early.
    root = tmp_path / "app"
    (root / ".git").mkdir(parents=True)
    (root / ".env").write_text("FOO=bar\n")
    server = root / "server"
    server.mkdir()
    (server / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    anchor = server / "xxvi"
    anchor.mkdir()

    found = find_upwards(".env", anchor)
    assert found is not None
    assert found.resolve() == (root / ".env").resolve()


def test_shape_2_tarball_or_ci_deploy_with_no_git_resolves_env_at_the_root(tmp_path):
    # THIS is the case that was broken. No .git anywhere (a tarball or CI
    # artifact excludes it). .env and .env.example -- both committed, both
    # travel with the artifact -- at the true root; pyproject.toml one level
    # below, in server/. With pyproject.toml as the fallback sentinel, the
    # boundary landed at server/ -- one directory too shallow -- and the
    # walk halted before ever reaching the root .env, returning None and
    # silently falling through to class defaults.
    root = tmp_path / "app"
    root.mkdir()
    (root / ".env").write_text("FOO=bar\n")
    (root / ".env.example").write_text("FOO=\n")
    server = root / "server"
    server.mkdir()
    (server / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    anchor = server / "xxvi"
    anchor.mkdir()

    found = find_upwards(".env", anchor)
    assert found is not None
    assert found.resolve() == (root / ".env").resolve()


def test_shape_3_docker_with_no_env_file_is_graceful_and_real_env_vars_still_work(
    tmp_path, monkeypatch
):
    # No .env, no .env.example, no .git anywhere -- config supplied entirely
    # via real environment variables, the documented Docker path. Must not
    # raise; must resolve to "nothing found" gracefully, and a real env var
    # must still reach Settings through the normal pydantic-settings
    # precedence once nothing is found on disk.
    root = tmp_path / "app"
    server = root / "server"
    anchor = server / "xxvi"
    anchor.mkdir(parents=True)

    assert find_upwards(".env", anchor) is None

    monkeypatch.chdir(anchor)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://docker-env/xxvi")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.database_url == "postgresql+asyncpg://docker-env/xxvi"
    finally:
        get_settings.cache_clear()


def test_shape_4_hostile_parent_env_above_the_sentinel_is_never_found(tmp_path):
    # A stranger .env sitting in an ancestor above the sentinel (a shared
    # machine's home directory, say) must never be picked up.
    (tmp_path / ".env").write_text("SECRET=leaked\n")
    root = tmp_path / "app"
    (root / ".git").mkdir(parents=True)
    server = root / "server"
    anchor = server / "xxvi"
    anchor.mkdir(parents=True)

    assert find_upwards(".env", anchor) is None


def test_shape_4_hostile_parent_is_also_blocked_under_the_env_example_fallback(tmp_path):
    # Same hostile-parent shape, but with no .git anywhere -- the
    # .env.example fallback sentinel must bound the walk just as strictly.
    (tmp_path / ".env").write_text("SECRET=leaked\n")
    root = tmp_path / "app"
    root.mkdir()
    (root / ".env.example").write_text("FOO=\n")
    server = root / "server"
    anchor = server / "xxvi"
    anchor.mkdir(parents=True)

    assert find_upwards(".env", anchor) is None


def test_a_nearer_env_example_does_not_stop_the_walk_before_a_farther_git(tmp_path):
    # Defense in depth for the sentinel *priority*, not just which markers
    # are in the set: if a nested .env.example ever ends up closer to the
    # anchor than the true .git root (e.g. a server/-local one added for
    # some other reason), .git must still win. Checking the whole chain for
    # .git before falling back to .env.example is what makes that true --
    # a literal "first ancestor with either marker, in walk order" check
    # would stop at the nearer .env.example instead.
    #
    # tmp_path/
    #   repo/.git/                 <- true boundary
    #   repo/.env                  <- must still be found
    #   repo/server/.env.example   <- nearer, must NOT stop the walk early
    #   repo/server/xxvi/anchor/   <- anchor
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".env").write_text("FOO=bar\n")
    server = repo / "server"
    server.mkdir()
    (server / ".env.example").write_text("FOO=\n")
    anchor = server / "xxvi" / "anchor"
    anchor.mkdir(parents=True)

    found = find_upwards(".env", anchor)
    assert found is not None
    assert found.resolve() == (repo / ".env").resolve()


def test_a_file_at_the_sentinel_directory_itself_is_still_found(tmp_path):
    # The sentinel directory is the *last* one searched, not excluded from
    # the search -- a file living right alongside .git must still resolve.
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".env").write_text("FOO=bar\n")
    anchor = repo / "pkg" / "anchor"
    anchor.mkdir(parents=True)

    found = find_upwards(".env", anchor)
    assert found is not None
    assert found.resolve() == (repo / ".env").resolve()


def test_a_file_between_anchor_and_the_sentinel_is_found_normally(tmp_path):
    repo = tmp_path / "repo"
    pkg = repo / "pkg"
    (repo / ".git").mkdir(parents=True)
    pkg.mkdir(parents=True)
    (pkg / ".env").write_text("FOO=bar\n")
    anchor = pkg / "anchor"
    anchor.mkdir(parents=True)

    found = find_upwards(".env", anchor)
    assert found is not None
    assert found.resolve() == (pkg / ".env").resolve()


def test_with_no_sentinel_anywhere_the_walk_is_bounded_to_none(tmp_path):
    # No .git, no .env.example anywhere in this synthetic tree -- there is
    # no boundary to enforce, and (as of this fix) no unbounded fallback
    # either. A stray same-named file sitting further up an unrelated
    # ancestor (a bare-container build context under some deep tmp/build
    # path, say) must never be picked up just because nothing closer marked
    # a boundary. Returns None immediately rather than walking to the
    # filesystem root.
    (tmp_path / "far.env").write_text("FOO=bar\n")
    anchor = tmp_path / "a" / "b" / "c"
    anchor.mkdir(parents=True)

    assert find_upwards("far.env", anchor) is None


def test_docker_build_context_has_no_sentinel_and_resolves_to_none(tmp_path):
    # The actual shape server/Dockerfile produces: `COPY xxvi ./xxvi`,
    # `COPY pyproject.toml ./` land at /app with no `.git` and no
    # `.env.example` copied into the image (only xxvi/, alembic/,
    # alembic.ini, and pyproject.toml are). If a stray same-named file
    # happened to exist somewhere above the image's build context on the
    # host filesystem during `docker build`, an unbounded walk could still
    # only ever see inside the image at container *runtime* -- but this
    # pins the container-shaped case directly: no sentinel anywhere in the
    # image means find_upwards(".env", ...) must resolve to None, not raise
    # and not wander off to "/".
    app = tmp_path / "app"
    (app / "xxvi").mkdir(parents=True)
    (app / "pyproject.toml").write_text("[project]\nname = 'xxvi'\n")
    (app / "alembic.ini").write_text("[alembic]\n")
    anchor = app / "xxvi"

    assert find_upwards(".env", anchor) is None

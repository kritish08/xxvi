# Postgres integration suite

## Why this is separate from `tests/`

Every one of the ~338 tests in `tests/` runs against SQLite in-memory. That
is deliberate and stays that way — the fast suite runs in a few seconds,
which is what makes the mutation-testing loop viable. But SQLite's
`StaticPool` fixture used everywhere in `tests/conftest.py` secretly
serializes every session in a test through one shared connection, which
makes any conclusion drawn from it about *concurrent* access unsound. Three
separate Criticals on this project were concurrency races that SQLite
structurally cannot detect, and one shared fixture was found to produce a
confidently wrong result on the money path: an 8-way race reported "1
success, 7 conflicts" — exactly the expected pass condition — while leaving
no row in the database at all.

This directory covers only what SQLite cannot prove: real concurrent
connections racing real Postgres MVCC (vault releases, gate attempts,
segment tokens), the actual `alembic` migration scripts (the fast suite
builds its schema from `Base.metadata.create_all()` and never runs a
migration at all), and a few places where SQLite's emulation of a Postgres
feature (`timestamptz`, `UPDATE ... RETURNING`) diverges from the real
thing. It does not re-test business logic the fast suite already covers.

## Which database this targets

A dedicated Neon branch, `test-integration` (project `xxvi`,
`falling-dawn-59106661`), forked from `main`. **Never point this suite at
`main`** — that branch backs the real event and the real gift-card codes.

Read the connection string from the `PG_TEST_URL` environment variable (the
`+asyncpg` **direct**, non-pooler endpoint — the pooler can reject
session-level DDL, which the migration tests need):

```
export PG_TEST_URL="postgresql+asyncpg://neondb_owner:<password>@<test-integration-branch-direct-endpoint>/neondb?ssl=require"
```

Get the current direct endpoint for `test-integration` from the Neon
console or `mcp__Neon__get_connection_string` (branch `test-integration`,
then drop the `-pooler` suffix from the hostname and switch `postgresql://`
to `postgresql+asyncpg://`). Do not hardcode it here or in `.env` — this
suite is meant to run correctly on the day the branch gets recreated with a
new endpoint too.

## Running it

```
cd server
PG_TEST_URL="postgresql+asyncpg://...test-integration-endpoint.../neondb?ssl=require" \
  .venv/bin/python -m pytest -m pg -q
```

Without `PG_TEST_URL` set, the entire suite (every test carrying the `pg`
marker, registered in `pyproject.toml`) is skipped cleanly at collection
time — no fixture runs, nothing touches the network — so a plain
`pytest -q` from `server/` is unaffected and still reports the fast
suite's count.

## What it does to the branch

Every fixture uses `NullPool`: each `sessionmaker()` call opens a genuinely
separate physical connection, the same shape independent request handlers
get in production. A pooled or shared connection cannot model a race —
that is exactly how the false-confidence result described above happened.

Every test cleans up its own data in FK-safe order
(`run_events`, `trophies_earned`, `consumed_tokens`, `code_releases`,
`gate_attempts` before `runs` before `accounts`) so the branch is empty
when the suite finishes. `tests/integration/test_migrations_pg.py` goes
further: it drops the entire `public` schema and rebuilds it from nothing
via `alembic upgrade head` as its own setup, and always restores the
schema to `head` on the way out (including on assertion failure), since
every other file in this directory assumes the schema already exists.

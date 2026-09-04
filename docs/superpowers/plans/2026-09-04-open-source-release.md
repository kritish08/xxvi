# XXVI Open-Source Release — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn XXVI from a private one-night artifact into a public repository that a stranger can read, understand, and actually run — with the recipient, the gift, the questions, the trophies, and the number of acts all supplied by them rather than baked in.

**Architecture:** The content layer is already config-driven and validated by Pydantic at load time; almost nothing here invents new structure. Three hardcoded `2`s (rewards, checkpoint gates, checkpoint hashes) become act-count-driven, the reward label gains a load-time length bound, and the repository gains the front door it never had. **No database migration is required by any task in this plan** — verified: `GateAttempt.gate_id` is a plain `String(32)`, `CodeRelease.reward_id` is an untyped `Integer`, and `Run.cleared_segments` is a JSON list carrying everything a derived score needs.

**Tech Stack:** Python 3.12 · FastAPI · Pydantic v2 / pydantic-settings · SQLAlchemy 2 (async) · Alembic · pytest · React 19 + TypeScript · Vite · Vitest + Testing Library · Docker Compose · Caddy

**Spec:** `docs/superpowers/specs/2026-09-04-open-source-release-design.md`

## Global Constraints

- **TDD is not optional.** Every behavioural task writes a failing test first, watches it fail for the right reason, then implements. This codebase was built that way and the tests are the reason it survived a live run.
- **No database migrations.** If a task appears to need one, STOP and raise it — spec §8 forbids adding one silently.
- **Never weaken a vault invariant.** Operator approval required; at-most-once per `(run, reward)` enforced by the DB unique constraint, not application logic; the code value never logged, never persisted, never in an exception message; a dry run leaves the ledger untouched.
- **Never break wire compatibility with existing persisted data.** `checkpoint_gate(1)` must produce exactly `"checkpoint_1"`, the string already in the `gate_attempts` table.
- **Answers never reach the client.** No task may add `accept` to any response model or any client-facing payload.
- **`docs/design-system.md` is binding** for every CSS or UI change.
- **Commit messages end with:**
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_013yAbTUM3UxQxGCysek3KrG
  ```
- **Baseline before starting:** server `528 passed, 13 skipped, 1 failed`; web `173 passed` across 31 files. Task 1 fixes the failure. After every task both suites must be green.
- **Run the suites from the right directory:** server tests from `server/` via `.venv/bin/python -m pytest`; web tests from `web/` via `npx vitest run`. There is no `--timeout` flag configured for pytest in this project.

---

## File Structure

**Server — modified**
- `server/xxvi/settings.py` — reward codes and checkpoint hashes become act-indexed accessors
- `server/xxvi/gates/service.py` — `GateId` keeps `ACTIVATION`; checkpoints become a computed id
- `server/xxvi/api/run_service.py:195,393` — the `act == 1` ternary becomes `checkpoint_gate(act)`
- `server/xxvi/vault/service.py` — `_code_for` reads `REWARD_{n}_CODE`
- `server/xxvi/content/schema.py` — `Reward.id` bound to act count; `Reward.label` bounded; `Question.points` optional
- `server/xxvi/cli.py` — new `validate-config` and `emit-schema` subcommands
- `server/xxvi/main.py:93-99` — the startup warning stops claiming the demo is uncompletable

**Server — created**
- `server/xxvi/content/scoring.py` — pure derived-score function, no I/O
- `server/tests/test_content_leak.py` — pins "answers never reach the client"
- `server/tests/test_scoring.py`

**Web — modified**
- `web/src/games/SimonSays.tsx` — explicit locked state for the mistake window
- `web/src/shell/codereveal.css` — label wrap guard

**Repo root — created**
- `LICENSE` (MIT) · `README.md` · `.github/workflows/ci.yml` · `config/run.schema.json`

---

### Task 1: Make the go-live test independent of the wall clock

The suite currently fails for everyone who clones the repo, because a fixture hardcodes a date that is now in the past. Fixing this first is what makes CI (Task 2) possible.

**Files:**
- Modify: `server/tests/test_api_auth.py:9-17`

**Interfaces:**
- Consumes: nothing
- Produces: a green server suite (`529 passed, 13 skipped`), which every later task's verification depends on

- [ ] **Step 1: Reproduce the failure**

Run: `cd server && .venv/bin/python -m pytest tests/test_api_auth.py::test_session_reports_the_countdown_before_go_live -q`

Expected: FAIL with `assert True is False`. The fixture pins `go_live_iso="2026-08-20T00:00:00+05:30"`; that instant has passed, so the API correctly reports `live: true` and the test's premise is gone.

- [ ] **Step 2: Replace the hardcoded date with one computed relative to now**

In `server/tests/test_api_auth.py`, add the import and a module-level constant, then use it in the fixture:

```python
from datetime import UTC, datetime, timedelta

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
```

- [ ] **Step 3: Verify the whole file passes, not just the one test**

Run: `cd server && .venv/bin/python -m pytest tests/test_api_auth.py -q`

Expected: `7 passed`. Only one of the seven tests referenced live-ness, and it wanted `live is False`, so widening the window cannot break the other six.

- [ ] **Step 4: Verify the full suite is now green**

Run: `cd server && .venv/bin/python -m pytest -q`

Expected: `529 passed, 13 skipped`, zero failures.

- [ ] **Step 5: Commit**

```bash
git add server/tests/test_api_auth.py
git commit -m "fix: the auth suite failed on every clone once go-live passed"
```

---

### Task 2: LICENSE and CI

**Files:**
- Create: `LICENSE`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the green suite from Task 1
- Produces: a CI workflow later tasks extend with a `validate-config` step (Task 8)

- [ ] **Step 1: Write the MIT licence**

Create `LICENSE` with the standard MIT text, `Copyright (c) 2026 Kritish`. Match the licence Marauders ships under.

- [ ] **Step 2: Write the workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  server:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        working-directory: server
        run: pip install -e ".[dev]"
      - name: Test
        working-directory: server
        run: python -m pytest -q

  web:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: web/package-lock.json
      - name: Install
        working-directory: web
        run: npm ci
      - name: Test
        working-directory: web
        run: npx vitest run
```

- [ ] **Step 3: Confirm the dev extra actually exists**

Run: `grep -n "optional-dependencies" -A 12 server/pyproject.toml`

Expected: a `[project.optional-dependencies]` block containing a `dev` list with pytest. If the extra is named differently, use the real name in the workflow — do not invent one. If no extra exists, install from whatever the project actually uses and note it.

- [ ] **Step 4: Confirm the server suite needs no database service**

Run: `cd server && .venv/bin/python -m pytest -q 2>&1 | tail -3`

Expected: green with 13 skips. The skips are the Postgres integration tests under `tests/integration/`, which self-skip without a database — that is why the workflow needs no `services:` block. If they do NOT skip, stop and add a Postgres service to the workflow instead of pretending.

- [ ] **Step 5: Commit**

```bash
git add LICENSE .github/workflows/ci.yml
git commit -m "chore: MIT licence and CI running both suites"
```

---

### Task 3: Pin "answers never reach the client" with a test

The property holds today — `run_routes.py:166` builds `QuestionView(prompt=..., blank=...)` and never touches `accept`. Nothing enforces it. This makes it a rule instead of a habit.

**Files:**
- Create: `server/tests/test_content_leak.py`

**Interfaces:**
- Consumes: nothing
- Produces: nothing later tasks depend on

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_content_leak.py`. Note it asserts against the *response models*, which is what makes it a real guard: a future `QuestionView` that gained an `accept` field would fail here even if no test happened to exercise that route.

```python
"""The answers must never be serialisable to the client.

`accept` lives only in the server's RunConfig. A player who opens DevTools,
reads the network tab, or greps the JS bundle must find no path to the
answer. This is true today by construction -- `run_routes.py` builds
`QuestionView` field by field -- but nothing enforced it, so a later
refactor that swapped in `QuestionView(**question.model_dump())` would leak
every answer at once and no existing test would notice.
"""

from xxvi.api import run_routes
from xxvi.content.schema import Question


def test_the_question_view_sent_to_the_client_has_no_answer_field():
    leaked = {"accept", "points"} & set(run_routes.QuestionView.model_fields)
    assert not leaked, f"QuestionView exposes {sorted(leaked)} to the client"


def test_the_question_view_carries_strictly_fewer_fields_than_the_config_model():
    # Guards the general shape rather than one field name: whatever the
    # config model grows, the client-facing view must stay a deliberate
    # subset chosen field by field.
    assert set(run_routes.QuestionView.model_fields) < set(Question.model_fields)


def test_a_serialised_question_view_contains_no_accepted_answer():
    view = run_routes.QuestionView(prompt="Which game?", blank="___ __")
    assert "GTA" not in view.model_dump_json()
```

- [ ] **Step 2: Run it**

Run: `cd server && .venv/bin/python -m pytest tests/test_content_leak.py -q`

Expected: PASS, all three. This test documents existing correct behaviour rather than driving new code, so green on the first run is the correct outcome — but read the failure carefully if it is not, because that would mean the property is already broken.

- [ ] **Step 3: Prove the test can actually fail**

Temporarily add `accept: list[str] = []` to `QuestionView` in `server/xxvi/api/run_routes.py`, re-run the test, and confirm it FAILS. Then revert. A guard nobody has watched fail is not a guard.

- [ ] **Step 4: Confirm the revert**

Run: `cd server && git diff --stat server/xxvi/api/run_routes.py`

Expected: no output. The file is unchanged.

- [ ] **Step 5: Commit**

```bash
git add server/tests/test_content_leak.py
git commit -m "test: pin that question answers never reach the client"
```

---

### Task 4: Checkpoint gates work for any number of acts

`GateId` has fixed `CHECKPOINT_1` / `CHECKPOINT_2` members, and `run_service.py` picks between them with `GateId.CHECKPOINT_1 if act == 1 else GateId.CHECKPOINT_2` in two places. With three acts, act 3 silently accepts act 2's checkpoint code.

**Files:**
- Modify: `server/xxvi/gates/service.py:9-13,42-43`
- Modify: `server/xxvi/api/run_service.py:195,393`
- Modify: `server/xxvi/settings.py`
- Test: `server/tests/test_gates.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `xxvi.gates.service.checkpoint_gate(act: int) -> str` — returns `f"checkpoint_{act}"`
  - `Settings.checkpoint_hash(act: int) -> str`
  - Task 5 follows the identical pattern for reward codes

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_gates.py`:

```python
def test_checkpoint_gate_ids_match_the_strings_already_in_the_database():
    # gate_attempts.gate_id is a plain String(32) holding these literals for
    # every run ever recorded. Changing the shape of act 1 and 2's ids would
    # orphan existing lockout rows, so the generalisation must reproduce them
    # exactly, not merely produce something consistent.
    from xxvi.gates.service import checkpoint_gate

    assert checkpoint_gate(1) == "checkpoint_1"
    assert checkpoint_gate(2) == "checkpoint_2"


def test_checkpoint_gate_extends_past_the_two_acts_xxvi_shipped_with():
    from xxvi.gates.service import checkpoint_gate

    assert checkpoint_gate(3) == "checkpoint_3"
    assert checkpoint_gate(7) == "checkpoint_7"


def test_a_third_act_does_not_reuse_the_second_acts_checkpoint_hash():
    # The bug this closes: `CHECKPOINT_1 if act == 1 else CHECKPOINT_2` sent
    # every act above 2 to act 2's gate, so act 3 would have opened to act 2's
    # code -- releasing act 3's reward to someone who never cleared act 3.
    from xxvi.settings import Settings

    settings = Settings(checkpoint_1_hash="h1", checkpoint_2_hash="h2")
    assert settings.checkpoint_hash(3) == ""
    assert settings.checkpoint_hash(3) != settings.checkpoint_hash(2)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd server && .venv/bin/python -m pytest tests/test_gates.py -q -k checkpoint_gate or third_act`

Expected: FAIL with `ImportError: cannot import name 'checkpoint_gate'`.

- [ ] **Step 3: Add the computed gate id**

In `server/xxvi/gates/service.py`, keep `GateId` for `ACTIVATION` and add:

```python
def checkpoint_gate(act: int) -> str:
    """The gate id for an act's checkpoint.

    Returns the same literals the old `GateId.CHECKPOINT_1` / `CHECKPOINT_2`
    members produced -- "checkpoint_1", "checkpoint_2" -- because those
    strings are already persisted in `gate_attempts.gate_id` for every run
    recorded to date. This is a StrEnum being replaced by a function purely
    so the set of gates can follow `acts` in config instead of being fixed
    at two; it is deliberately NOT a change of format.
    """
    return f"checkpoint_{act}"
```

Replace the hardcoded dict at lines 42-43 with a lookup keyed on the act, reading `Settings.checkpoint_hash(act)`.

- [ ] **Step 4: Add the settings accessor**

In `server/xxvi/settings.py`:

```python
    def checkpoint_hash(self, act: int) -> str:
        """The bcrypt hash of act N's checkpoint code.

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
```

Add `import os` at the top of the file if absent.

- [ ] **Step 5: Replace both ternaries**

In `server/xxvi/api/run_service.py` at lines 195 and 393, replace
`gate = GateId.CHECKPOINT_1 if act == 1 else GateId.CHECKPOINT_2`
with `gate = checkpoint_gate(act)`, importing `checkpoint_gate` from `xxvi.gates.service`.

- [ ] **Step 6: Make `assert_production_ready` check every configured act**

Replace the two hardcoded `checkpoint_1_hash` / `checkpoint_2_hash` emptiness checks with a loop over `range(1, get_config().acts + 1)` calling `self.checkpoint_hash(act)`, naming each missing act in the offender message. Keep the existing message style: name every offender in one exception rather than failing on the first.

- [ ] **Step 7: Run the gate and run-service suites**

Run: `cd server && .venv/bin/python -m pytest tests/test_gates.py tests/test_api_run.py tests/test_run_service_concurrency.py -q`

Expected: PASS, including the new tests.

- [ ] **Step 8: Run the full suite**

Run: `cd server && .venv/bin/python -m pytest -q`

Expected: green. Pay attention to `tests/integration/test_gates_pg.py` if Postgres is available locally — it exercises the persisted `gate_id` strings this task must not change.

- [ ] **Step 9: Commit**

```bash
git add server/xxvi/gates/service.py server/xxvi/api/run_service.py server/xxvi/settings.py server/tests/test_gates.py
git commit -m "feat: checkpoint gates follow the act count instead of being fixed at two"
```

---

### Task 5: Rewards work for any number of acts

`Reward.id` is `Literal[1, 2]` and `VaultService._code_for` raises `UnknownReward` for anything else — *after* `apply()` has already advanced the state machine past the checkpoint. A three-act config loads clean and 500s at the moment the gift is supposed to land.

**Files:**
- Modify: `server/xxvi/content/schema.py` (`Reward.id`, `RunConfig.counts_line_up`)
- Modify: `server/xxvi/vault/service.py:_code_for`
- Modify: `server/xxvi/settings.py` (`reward_code`, `assert_production_ready`)
- Test: `server/tests/test_vault.py`, `server/tests/test_content.py`

**Interfaces:**
- Consumes: `Settings.checkpoint_hash` pattern from Task 4
- Produces: `Settings.reward_code(reward_id: int) -> str`

- [ ] **Step 1: Create the shared config factory**

Every existing test in `tests/test_content.py` spells out a whole valid config dict inline, which is why they are long. There is **no `make_config` helper today** — create one, in its own file so `tests/test_scoring.py` (Task 7) can import it too.

Create `server/tests/factories.py`:

```python
"""Config builders for tests.

Every test in test_content.py predating this file spells out a full valid
config dict inline. Those are left alone rather than churned; new tests
build from here so the assertion is not buried under thirty lines of
scaffolding.
"""

from xxvi.content.schema import RunConfig


def make_config(**overrides) -> RunConfig:
    """A valid RunConfig, overriding only what the caller cares about.

    `acts` and `segments_per_act` are consumed here rather than passed
    through, because every other section's size is derived from them --
    questions, games, trophies and rewards all have to line up or
    `counts_line_up` rejects the result.
    """
    acts = overrides.pop("acts", 1)
    segments_per_act = overrides.pop("segments_per_act", 1)
    total = acts * segments_per_act
    base = {
        "recipient": "X",
        "acts": acts,
        "segments_per_act": segments_per_act,
        "questions": [
            {"prompt": f"p{i}", "accept": ["a"], "roast": "r"}
            for i in range(1, total + 1)
        ],
        "games": [
            {"segment": i, "mechanic": "simon", "params": {}}
            for i in range(1, total + 1)
        ],
        "trophies": (
            [{"id": f"game-{i}", "name": "n", "grade": "bronze"} for i in range(1, total + 1)]
            + [{"id": f"question-{i}", "name": "n", "grade": "bronze"} for i in range(1, total + 1)]
            + [{"id": f"act-{i}", "name": "n", "grade": "gold"} for i in range(1, acts + 1)]
            + [{"id": "platinum", "name": "n", "grade": "platinum"}]
        ),
        "rewards": [
            {"id": i, "after_act": i, "label": f"r{i}"} for i in range(1, acts + 1)
        ],
        "copy": {"coming_soon": "a", "teaser": "b", "how_to_play": "c", "closing": "d"},
    }
    base.update(overrides)
    return RunConfig.model_validate(base)
```

Verify it works before building on it:

Run: `cd server && .venv/bin/python -c "from tests.factories import make_config; print(make_config(acts=2, segments_per_act=4).total_segments)"`
Expected: `8`

- [ ] **Step 2: Rewrite the test this task deliberately breaks**

`tests/test_content.py:131` currently asserts `Reward(id=3, ...)` **raises** — that is the behaviour Task 5 removes, so it will fail. Do not delete the test: the guarantee it protects (a bad reward id fails at load, never at the checkpoint) still matters, it just moves from the field to `counts_line_up`. Replace it with:

```python
def test_a_reward_id_outside_the_act_range_fails_at_load_not_at_the_checkpoint():
    # This guarantee has MOVED, not gone. It used to be `Reward.id:
    # Literal[1, 2]`, which also made a third ACT impossible. The bound is
    # now the configured act count, checked in `counts_line_up` -- but the
    # failure it prevents is unchanged: an unservable reward id used to load
    # cleanly and raise UnknownReward at submit_checkpoint, AFTER the state
    # machine had advanced the run past the checkpoint.
    from tests.factories import make_config

    with pytest.raises(ValidationError, match="reward"):
        make_config(
            acts=2,
            segments_per_act=1,
            rewards=[
                {"id": 1, "after_act": 1, "label": "ok"},
                {"id": 9, "after_act": 2, "label": "no such reward"},
            ],
        )
```

- [ ] **Step 3: Write the failing tests**

Add to `server/tests/test_content.py`:

```python
def test_a_three_act_config_with_three_rewards_is_accepted():
    # Before this change `Reward.id` was Literal[1, 2], so a third reward was
    # rejected at load -- and a third ACT with only two rewards loaded fine
    # and then 500'd at the act-3 checkpoint, after the state machine had
    # already advanced past it.
    from tests.factories import make_config

    config = make_config(acts=3, segments_per_act=2)
    assert len(config.rewards) == 3
    assert [r.id for r in config.rewards] == [1, 2, 3]


def test_duplicate_reward_ids_are_rejected():
    from tests.factories import make_config

    with pytest.raises(ValidationError, match="reward"):
        make_config(
            acts=2,
            segments_per_act=1,
            rewards=[
                {"id": 1, "after_act": 1, "label": "first"},
                {"id": 1, "after_act": 2, "label": "same id again"},
            ],
        )
```

Add to `server/tests/test_vault.py`:

```python
async def test_a_third_reward_resolves_its_own_code(monkeypatch, sessionmaker):
    monkeypatch.setenv("REWARD_3_CODE", "THIRD-CODE-XYZ")
    settings = Settings(reward_1_code="one", reward_2_code="two")
    vault = VaultService(sessionmaker, settings)
    assert vault.code_for(3) == "THIRD-CODE-XYZ"


async def test_an_unconfigured_reward_still_raises_rather_than_returning_empty(sessionmaker):
    # The failure mode this preserves: silently returning "" would print a
    # blank code at the one moment that matters and look like it worked.
    vault = VaultService(sessionmaker, Settings())
    with pytest.raises(UnknownReward):
        vault.code_for(4)
```

- [ ] **Step 4: Run them to verify they fail**

Run: `cd server && .venv/bin/python -m pytest tests/test_content.py tests/test_vault.py -q`

Expected: FAIL — the content tests on `Literal[1, 2]` validation, the vault tests on `UnknownReward` for id 3.

- [ ] **Step 5: Loosen the schema and tie it to the act count**

In `server/xxvi/content/schema.py`, change `Reward.id` from `Literal[1, 2]` to `int = Field(ge=1)`, and replace the pinning comment with one explaining that the bound now comes from `counts_line_up`. In `counts_line_up`, add: every reward id must be within `1..acts`, and reward ids must be unique. The existing check that `after_act` covers `1..acts` exactly once stays.

- [ ] **Step 6: Add the settings accessor**

In `server/xxvi/settings.py`, mirroring Task 4's `checkpoint_hash`:

```python
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
```

- [ ] **Step 7: Rewrite `_code_for` without changing any invariant**

In `server/xxvi/vault/service.py`:

```python
    def _code_for(self, reward_id: int) -> str:
        if self._settings.dry_run:
            # A rehearsal must never emit -- or even read -- the real value.
            return f"DRY-RUN-REWARD-{reward_id}"
        code = self._settings.reward_code(reward_id)
        if not code:
            raise UnknownReward(f"no code configured for reward {reward_id}")
        return code
```

Note the ordering: the `dry_run` branch stays FIRST, exactly as before, so a rehearsal never reads a real code even to validate it.

- [ ] **Step 8: Generalise the production check**

In `assert_production_ready`, replace the two hardcoded reward checks with a loop over the configured rewards, calling `self.reward_code(r.id)` and naming each offender. Keep the existing wording pattern.

- [ ] **Step 9: Run the tests**

Run: `cd server && .venv/bin/python -m pytest tests/test_vault.py tests/test_content.py tests/test_settings.py -q`

Expected: PASS.

- [ ] **Step 10: Run the full suite**

Run: `cd server && .venv/bin/python -m pytest -q`

Expected: green. `tests/integration/test_vault_pg.py` covers the unique-constraint behaviour that must not have moved.

- [ ] **Step 11: Commit**

```bash
git add server/xxvi/content/schema.py server/xxvi/vault/service.py server/xxvi/settings.py server/tests/
git commit -m "feat: rewards follow the act count instead of being fixed at two"
```

---

### Task 6: Bound the reward label so it cannot overflow the reveal

`.reveal__title` renders at `--type-display` — `clamp(4rem, 9vw, 9rem)`, up to 144px — with no `max-width` and no wrap guard. The shipped label was 26 characters and broke at spaces; a longer one, or a single unbroken word, runs off screen. The code itself is already safe.

**Files:**
- Modify: `server/xxvi/content/schema.py` (`Reward.label`)
- Modify: `web/src/shell/codereveal.css`
- Test: `server/tests/test_content.py`

**Interfaces:**
- Consumes: Task 5's `Reward` model
- Produces: nothing later tasks depend on

- [ ] **Step 1: Write the failing test**

```python
def test_an_overlong_reward_label_is_rejected_at_load_not_at_midnight():
    # .reveal__title renders at up to 144px with no truncation -- this is the
    # one screen the whole run exists for, so a label that would overflow it
    # must fail when the config is loaded, not when the gift lands.
    from tests.factories import make_config

    with pytest.raises(ValidationError, match="label"):
        make_config(rewards=[{"id": 1, "after_act": 1, "label": "x" * 200}])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd server && .venv/bin/python -m pytest tests/test_content.py -q -k overlong`

Expected: FAIL — a 200-character label is currently accepted.

- [ ] **Step 3: Bound the field**

```python
class Reward(BaseModel):
    id: int = Field(ge=1)
    after_act: int = Field(ge=1)
    # Bounded because the reveal renders this at --type-display (up to 144px)
    # with no truncation and no ellipsis -- see web/src/shell/codereveal.css.
    # The limit is a rendering constraint, so it is enforced where a bad value
    # can still be fixed cheaply: config load, not the reveal itself.
    label: str = Field(min_length=1, max_length=48)
```

- [ ] **Step 4: Harden the CSS**

In `web/src/shell/codereveal.css`, add to `.reveal__title`:

```css
  max-width: 90vw;
  overflow-wrap: anywhere;
  text-wrap: balance;
```

`overflow-wrap: anywhere` handles the single-unbroken-word case that word-based wrapping cannot; `max-width` matches `.reveal__code`'s existing `90vw`.

- [ ] **Step 5: VERIFY THE LIMIT VISUALLY — do not skip this**

48 is an arithmetic guess, not a measurement. Run the app, reach a reveal with a 48-character label, and look at it at both a narrow phone width (~360px) and a desktop width (~1440px).

Use the `run` skill to launch the app. If reaching a real reveal is slow, render `CodeReveal` directly in a scratch Vite route or a Vitest browser-mode snapshot — but *look at rendered output*, do not reason about it.

If 48 characters overflows or wraps to more than three lines, **lower the number in both the schema and this plan's record** and say so in the commit message. Report the width you actually tested at.

- [ ] **Step 6: Run both suites**

Run: `cd server && .venv/bin/python -m pytest -q` and `cd web && npx vitest run`

Expected: both green. If any existing fixture uses a reward label longer than the final limit, fix the fixture — the limit is the product decision.

- [ ] **Step 7: Commit**

```bash
git add server/xxvi/content/schema.py web/src/shell/codereveal.css server/tests/test_content.py
git commit -m "fix: a long gift label could run off the reveal screen"
```

---

### Task 7: Optional per-question points, derived not stored

Spec §2: `points` is optional and absent by default; if no question declares points, no score UI appears anywhere. Points gate nothing — progression stays on trophies and segments.

**Files:**
- Modify: `server/xxvi/content/schema.py` (`Question.points`)
- Create: `server/xxvi/content/scoring.py`
- Create: `server/tests/test_scoring.py`

**Interfaces:**
- Consumes: `RunConfig` from Task 5
- Produces: `xxvi.content.scoring.score_for(config: RunConfig, cleared_segments: list[int]) -> int | None` — returns `None` when scoring is disabled, which is the signal the UI uses to render nothing

- [ ] **Step 1: Confirm no migration is needed**

Run: `grep -n "cleared_segments" server/xxvi/persistence/models.py`

Expected: `cleared_segments: Mapped[list[int]] = mapped_column(JSON, default=list)`. A score is a pure function of the config and that list, so nothing new is persisted. **If this is not what you find, STOP** — Global Constraints forbid adding a migration without raising it.

- [ ] **Step 2: Write the failing tests**

Create `server/tests/test_scoring.py`:

```python
"""Scoring is derived, never stored.

A score is a pure function of (config, cleared_segments), so enabling or
retuning points never needs a migration and never touches the run row --
which is what keeps it clear of the optimistic-concurrency machinery on
`Run.version`.
"""

from tests.factories import make_config
from xxvi.content.scoring import score_for

QUESTIONS_WITH_POINTS = [
    {"prompt": "p1", "accept": ["a"], "roast": "r", "points": 100},
    {"prompt": "p2", "accept": ["a"], "roast": "r", "points": 50},
]
QUESTIONS_PARTIAL_POINTS = [
    {"prompt": "p1", "accept": ["a"], "roast": "r", "points": 100},
    {"prompt": "p2", "accept": ["a"], "roast": "r"},
]


def _scored(questions):
    return make_config(acts=1, segments_per_act=2, questions=questions)


def test_scoring_is_off_when_no_question_declares_points():
    # The whole feature must be invisible unless someone opts in. None is the
    # signal the UI keys off to render no score at all -- distinct from 0,
    # which means "scoring is on and you have not scored yet".
    config = make_config(acts=1, segments_per_act=2)
    assert score_for(config, cleared_segments=[1, 2]) is None


def test_a_cleared_segment_contributes_its_questions_points():
    assert score_for(_scored(QUESTIONS_WITH_POINTS), cleared_segments=[1, 2]) == 150


def test_an_uncleared_segment_contributes_nothing():
    assert score_for(_scored(QUESTIONS_WITH_POINTS), cleared_segments=[1]) == 100


def test_scoring_is_on_even_if_only_some_questions_declare_points():
    # A question with no `points` is worth 0, not a reason to disable scoring.
    assert score_for(_scored(QUESTIONS_PARTIAL_POINTS), cleared_segments=[1, 2]) == 100


def test_no_cleared_segments_scores_zero_not_none_when_points_are_configured():
    assert score_for(_scored(QUESTIONS_WITH_POINTS), cleared_segments=[]) == 0
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd server && .venv/bin/python -m pytest tests/test_scoring.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'xxvi.content.scoring'`.

- [ ] **Step 4: Add the optional field**

In `server/xxvi/content/schema.py`, on `Question`:

```python
    # Optional and off by default. Points are cosmetic: they are displayed,
    # never checked. Progression is trophies and segments, and `core/` never
    # learns this field exists.
    points: int | None = Field(default=None, ge=0)
```

- [ ] **Step 5: Write the scoring function**

Create `server/xxvi/content/scoring.py`:

```python
from xxvi.content.schema import RunConfig


def score_for(config: RunConfig, cleared_segments: list[int]) -> int | None:
    """Total points for the segments cleared so far, or None if scoring is off.

    Pure: no I/O, no session, no run row. The caller passes
    `Run.cleared_segments` straight in. Returning None rather than 0 when
    nobody configured points is what lets the UI distinguish "this run has no
    score" from "this run has scored nothing yet" -- rendering a bold 0 to
    someone who never opted into scoring would be a worse bug than showing
    no score at all.
    """
    if all(q.points is None for q in config.questions):
        return None
    total = 0
    for segment in cleared_segments:
        # Segments are 1-indexed and validated to cover 1..total_segments
        # exactly once, so this index is always in range for a loaded config.
        question = config.questions[segment - 1]
        total += question.points or 0
    return total
```

- [ ] **Step 6: Run the tests**

Run: `cd server && .venv/bin/python -m pytest tests/test_scoring.py -q`

Expected: PASS, all five.

- [ ] **Step 7: Run the full suite**

Run: `cd server && .venv/bin/python -m pytest -q`

Expected: green. Adding an optional field with a default cannot break existing configs; if something fails, the field was not actually optional.

- [ ] **Step 8: Commit**

```bash
git add server/xxvi/content/schema.py server/xxvi/content/scoring.py server/tests/test_scoring.py
git commit -m "feat: optional per-question points, derived from cleared segments"
```

---

### Task 8: JSON Schema and `validate-config`

The highest-leverage item for "anyone can edit this easily", and nearly free because the validation already exists.

**Files:**
- Modify: `server/xxvi/cli.py` (two new subcommands)
- Create: `config/run.schema.json` (generated, committed)
- Modify: `.github/workflows/ci.yml`
- Test: `server/tests/test_cli.py`

**Interfaces:**
- Consumes: the `RunConfig` model as it stands after Tasks 5-7
- Produces: `python -m xxvi.cli validate-config <path>` exiting 0 on valid, non-zero with readable errors on invalid; `python -m xxvi.cli emit-schema` writing `config/run.schema.json`

- [ ] **Step 1: Write the failing tests**

Add to `server/tests/test_cli.py`, following the invocation style the existing tests in that file use:

```python
def test_validate_config_accepts_the_shipped_example(capsys):
    assert cmd_validate_config("config/run.example.yaml") == 0


def test_validate_config_rejects_a_broken_file_with_a_readable_error(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("recipient: 'x'\nacts: 2\n")  # missing everything else
    assert cmd_validate_config(str(bad)) != 0
    out = capsys.readouterr().out + capsys.readouterr().err
    # A pydantic traceback is not an error message a stranger can act on.
    assert "questions" in out.lower()


def test_the_committed_schema_is_in_sync_with_the_model():
    # Catches the drift that made run.example.yaml stale: the schema is
    # generated, so a model change with a forgotten regeneration must fail
    # CI rather than ship a schema that lies to someone's editor.
    import json
    from pathlib import Path
    from xxvi.content.schema import RunConfig

    committed = json.loads(Path("config/run.schema.json").read_text())
    assert committed == RunConfig.model_json_schema()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd server && .venv/bin/python -m pytest tests/test_cli.py -q -k "validate_config or schema"`

Expected: FAIL — the functions and the file do not exist.

- [ ] **Step 3: Implement both subcommands**

In `server/xxvi/cli.py`, add `cmd_validate_config(path: str) -> int` and `cmd_emit_schema(out: str) -> int`, and register `validate-config` (positional `path`, defaulting to `config/run.yaml`) and `emit-schema` in the subparser block near lines 217-234, matching the existing style.

`cmd_validate_config` must catch `pydantic.ValidationError` and print one line per error as `<dotted.field.path>: <message>`. A raw traceback is not usable by someone editing YAML for the first time.

- [ ] **Step 4: Generate and commit the schema**

Run: `cd server && .venv/bin/python -m xxvi.cli emit-schema`

Expected: `config/run.schema.json` written. Add the schema reference as the first line of both `config/run.example.yaml` and `config/run.yaml`:

```yaml
# yaml-language-server: $schema=./run.schema.json
```

- [ ] **Step 5: Add validation to CI**

In `.github/workflows/ci.yml`, in the `server` job after the test step:

```yaml
      - name: Validate the shipped example config
        working-directory: server
        run: python -m xxvi.cli validate-config ../config/run.example.yaml
```

- [ ] **Step 6: Run the tests**

Run: `cd server && .venv/bin/python -m pytest tests/test_cli.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add server/xxvi/cli.py server/tests/test_cli.py config/run.schema.json config/run.example.yaml .github/workflows/ci.yml
git commit -m "feat: JSON Schema and validate-config so the YAML is editable without reading Python"
```

---

### Task 9: A playable demo config, and stop calling it uncompletable

Spec §4.1. `run.example.yaml` currently says `"Q1 placeholder"` / `"placeholder1"`, and the startup warning tells the operator the run "WILL NOT be completable like this" — which becomes false the moment the demo is real.

**Files:**
- Modify: `config/run.example.yaml` (rewrite)
- Modify: `server/xxvi/main.py:93-99`
- Test: `server/tests/test_main.py`

**Interfaces:**
- Consumes: `validate-config` from Task 8
- Produces: a config a stranger can actually finish

- [ ] **Step 1: Rewrite the example as a real, generic run**

Every question answerable by anyone (general knowledge, not private memories), generous `accept` lists, real trophy names, and **generic reward labels — no PSN framing** (spec §4.1). It must include the corrections the current file lacks:

- the `stack` mechanic with a `target`, replacing at least one `update` slot
- `lives` on both `trophy_run` slots
- the `# yaml-language-server:` line from Task 8

Keep `acts: 2, segments_per_act: 4`. Every reward label must be within the Task 6 limit.

- [ ] **Step 2: Validate it**

Run: `cd server && .venv/bin/python -m xxvi.cli validate-config ../config/run.example.yaml`

Expected: exit 0.

- [ ] **Step 3: Write the failing test for the warning**

Add to `server/tests/test_main.py`:

```python
async def test_the_example_content_warning_does_not_claim_the_demo_is_unplayable(
    sessionmaker, monkeypatch, caplog
):
    # The old wording ("The run WILL NOT be completable like this") described
    # placeholder content. The example is now a real playable demo, so that
    # sentence became false -- and it is the first thing anyone running this
    # from a clone sees in their logs.
    monkeypatch.setattr(main_module, "get_sessionmaker", lambda: sessionmaker)
    monkeypatch.setattr(main_module, "is_serving_example_content", lambda: True)
    app = create_app()
    with caplog.at_level(logging.WARNING, logger="xxvi.main"):
        async with lifespan(app):
            pass
    text = " ".join(record.message for record in caplog.records)
    assert "WILL NOT be completable" not in text
    # The existing test at the top of this file still requires the filename,
    # so the rewrite must keep it.
    assert "run.example.yaml" in text
    assert "demo" in text.lower()
```

This reuses the exact fixture style already at the top of `tests/test_main.py` — `monkeypatch.setattr(main_module, "is_serving_example_content", lambda: True)` — so no new scaffolding is needed.

- [ ] **Step 4: Run it to verify it fails**

Run: `cd server && .venv/bin/python -m pytest tests/test_main.py -q -k warning`

Expected: FAIL on the old wording still being present.

- [ ] **Step 5: Rewrite the warning**

In `server/xxvi/main.py`, replace the warning body: say that `config/run.yaml` was not found, that the **playable demo config** is being served, that reward codes will be placeholders, and that a real run needs `config/run.yaml` plus real `REWARD_{n}_CODE` values. Update the surrounding comment, which also describes the old placeholder behaviour.

- [ ] **Step 6: Run both suites**

Run: `cd server && .venv/bin/python -m pytest -q` and `cd web && npx vitest run`

Expected: green.

- [ ] **Step 7: Play the demo end to end**

Use the `run` skill. Start from a clone-like state (no `config/run.yaml`), boot with `docker compose up`, and **actually play through at least one full segment and one checkpoint** to confirm the demo reveals a placeholder code rather than erroring. Report what you saw.

- [ ] **Step 8: Commit**

```bash
git add config/run.example.yaml server/xxvi/main.py server/tests/test_main.py
git commit -m "feat: the example config is a playable demo, not placeholders"
```

---

### Task 10: The three Simon Says defects

All three live in the `MISTAKE_HOLD_MS = 900` window. Throughout it `phase` is still `"repeat"` and `finished.current` is still `false`, so `press()` keeps accepting input.

**Files:**
- Modify: `web/src/games/SimonSays.tsx:122-167,204`
- Test: `web/tests/simon.test.tsx`

**Interfaces:**
- Consumes: nothing
- Produces: nothing later tasks depend on

- [ ] **Step 1: Write the failing test for the burned tries**

`tests/simon.test.tsx` uses **real timers** with `waitFor`, not fake timers — follow that. Add:

```tsx
it("ignores presses during the pause after a mistake instead of eating more tries", async () => {
  // The bug: `press()` returns early only on `phase !== "repeat"`, but phase
  // stays "repeat" for the whole 900ms hold. Presses in that window appended
  // to an uncleared `entered.current`, compared against a meaningless
  // position, mismatched, and decremented attemptsLeft again -- three stray
  // presses could drain the pool at once and fire onFinish while a timeout
  // was still queued to setState on a dying component.
  const onFinish = vi.fn();
  const { container } = render(
    <SimonSays seed="s" params={{ length: 3, tries: 3 }} onFinish={onFinish} />,
  );
  const seq = await simonSequence("s", 3);
  await waitFor(() => expect(screen.getByText("your turn")).toBeDefined(), { timeout: 5000 });

  const litPips = () => container.querySelectorAll(".simon__pip.is-lit").length;
  expect(litPips()).toBe(3);

  const wrong = (seq[0] + 1) % 4;
  await userEvent.click(screen.getByLabelText(FACE_LABELS[wrong]));
  expect(litPips()).toBe(2);

  // Both of these land inside the 900ms hold.
  await userEvent.click(screen.getByLabelText(FACE_LABELS[wrong]));
  await userEvent.click(screen.getByLabelText(FACE_LABELS[wrong]));

  expect(litPips()).toBe(2);
  expect(onFinish).not.toHaveBeenCalled();
});
```

**If the two follow-up clicks take longer than 900ms of real time** the hold will have expired and the test will pass for the wrong reason. Confirm it fails against the current code (Step 4) — if it does not, switch that block to `vi.useFakeTimers()` with `userEvent.setup({ advanceTimers: vi.advanceTimersByTime })` and drive the hold explicitly. Do not leave a test that passes because it raced.

- [ ] **Step 2: Write the failing test for the misleading header**

```tsx
it("stops saying 'your turn' while the mistake is being shown", async () => {
  // Line 204 reads `phase === "watch" ? "watch…" : "your turn"`, so during
  // the hold the screen invited input the game was about to discard.
  const onFinish = vi.fn();
  render(<SimonSays seed="s" params={{ length: 3, tries: 3 }} onFinish={onFinish} />);
  const seq = await simonSequence("s", 3);
  await waitFor(() => expect(screen.getByText("your turn")).toBeDefined(), { timeout: 5000 });

  await userEvent.click(screen.getByLabelText(FACE_LABELS[(seq[0] + 1) % 4]));

  expect(screen.queryByText("your turn")).toBeNull();
});
```

- [ ] **Step 3: REPRODUCE the third defect before fixing it**

Spec §5.3: the "success flash never clears" report is **not confirmed from reading the code**. `setFlash({face, ok: true})` on a correct press is overwritten by the next press, and the mistake path clears it inside its timeout — so the mechanism is unclear.

Find the actual sequence that leaves a stale flash on screen and write a test that fails on it. A likely candidate worth trying first: the last correct press of a completed sequence sets a flash that nothing clears, so `is-right` persists on that face while `GameHost` transitions away. **If you cannot reproduce it, do not invent a fix** — say so, and report what you ruled out. A speculative fix to a bug nobody can demonstrate is worse than an open issue.

- [ ] **Step 4: Run the tests to verify they fail**

Run: `cd web && npx vitest run simon`

Expected: FAIL on the tries counter and the header text.

- [ ] **Step 5: Add an explicit locked state**

Do not infer input-acceptance from `phase` — that is what made these three bugs one bug. Add a dedicated ref or phase value (e.g. `phase === "mistake"`) set synchronously on the wrong press and cleared in the timeout. `press()` returns early on it, and the header renders a third string for it.

Also clear the pending timeout on unmount: keep its handle in a ref and clear it in the effect cleanup, so a component that goes away mid-hold cannot call `setState` afterwards.

- [ ] **Step 6: Run the tests**

Run: `cd web && npx vitest run simon`

Expected: PASS.

- [ ] **Step 7: Run the full web suite**

Run: `cd web && npx vitest run`

Expected: `173 passed` plus the new tests. `gamehost.test.tsx` and `console-game-retry.test.tsx` cover the surrounding flow.

- [ ] **Step 8: Play it**

Use the `run` skill, reach a Simon segment, deliberately make a mistake, and mash buttons during the pause. Confirm the tries counter drops by exactly one and the header does not say "your turn".

- [ ] **Step 9: Commit**

```bash
git add web/src/games/SimonSays.tsx web/tests/simon.test.tsx
git commit -m "fix: presses during Simon's mistake pause burned extra tries"
```

---

### Task 11: Generic deployment

`deploy/docker-compose.prod.yml` and `deploy/Caddyfile.prod` hardcode one specific host and domain, and encode one specific shared-server tenancy arrangement.

**Files:**
- Modify: `deploy/docker-compose.prod.yml`, `deploy/Caddyfile.prod`
- Create: `deploy/README.md`

**Interfaces:**
- Consumes: nothing
- Produces: nothing later tasks depend on

- [ ] **Step 1: Read both files and list every host-specific value**

Run: `cat deploy/docker-compose.prod.yml deploy/Caddyfile.prod`

Note every occurrence of the hostname, the domain, the network name, and the neighbouring-container assumptions.

- [ ] **Step 2: Replace specifics with variables, keep the reasoning**

Substitute `${SITE_DOMAIN}` and generic network names. **Keep the explanatory comments** — why it publishes no host ports, why it sits behind an existing proxy rather than taking 80/443. That reasoning is the interesting part for a reader and is exactly what a generic template usually throws away.

- [ ] **Step 3: Write `deploy/README.md`**

Two paths, honestly labelled: the simple case (this is the only thing on the box — it takes 80/443 itself) and the shared case (something already owns 80/443 — connect to its network and add a site block). Include the real lesson from the original deployment: **create the DNS record before adding the site block**, or ACME fails with "no valid A records" and can wedge on a stuck attempt.

Also record that `--force-recreate` is required for an `.env` change to take effect; a plain `up -d --build` will not recreate the container if the image is unchanged.

- [ ] **Step 4: Validate the Caddyfile still parses**

Run: `docker run --rm -v "$PWD/deploy:/w" -w /w caddy:latest caddy validate --config Caddyfile.prod --adapter caddyfile`

Expected: `Valid configuration`. If the variable substitution broke it, fix it now rather than at deploy time.

- [ ] **Step 5: Commit**

```bash
git add deploy/
git commit -m "chore: deployment config is generic, with the tenancy reasoning kept"
```

---

### Task 12: README and asset provenance

**Files:**
- Create: `README.md`
- Create: `web/public/audio/PROVENANCE.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: everything above
- Produces: the repository's front door

- [ ] **Step 1: Confirm the font licences — do not assume**

Run: `ls web/public/fonts/` and check the upstream licence for Archivo and IBM Plex. Both are believed to be SIL Open Font License, but **verify it and record the actual licence text or link**. If either is not redistributable, remove it and load from a CDN instead.

- [ ] **Step 2: Write the asset provenance file**

Create `web/public/audio/PROVENANCE.md`: the four music tracks are the author's own Gemini-generated output, redistributed under the repository's licence. The narration is OpenAI TTS output — record that and confirm the redistribution terms. Note that narration is currently disabled (`NARRATION_ENABLED = false`) and why.

- [ ] **Step 3: Update `.env.example` for N rewards**

Replace the fixed `REWARD_1_CODE` / `REWARD_2_CODE` pair with the `REWARD_{n}_CODE` and `CHECKPOINT_{n}_HASH` convention from Tasks 4-5, keeping the existing detailed comment about `ACTIVATION_CODE_HASH` needing the dashed form — that comment documents a real trap. Remove `SITE_DOMAIN`'s XXVI-specific wording.

- [ ] **Step 4: Write the README**

In the GeekOnPeak house voice — technical, specific, honest about tradeoffs. Cover:

- What it is, in two sentences, and that it ran once for real
- **Quickstart:** clone → `docker compose up` → play the demo, with no config step
- **Make it yours:** edit `config/run.yaml` (schema-backed autocomplete), set `REWARD_{n}_CODE`, run `validate-config`
- **Architecture,** and why: server-authoritative verification (`passed_client_side` is advisory and structurally ignored), optimistic concurrency on `Run.version`, insert-first-catch-unique-violation as the at-most-once idiom, the three-bus audio mix
- **What was cut and what is still imperfect** — including any Simon defect Task 10 could not reproduce
- Screenshots **taken against the demo config**, never real content (spec §7)
- Link to the GeekOnPeak write-up; MIT licence

- [ ] **Step 5: Verify the quickstart by actually doing it**

Clone the repo to a fresh directory, run the documented commands verbatim, and confirm the demo boots and is playable. **Fix the README to match reality rather than fixing your memory of it.** Report the exact commands that worked.

- [ ] **Step 6: Final full verification**

Run: `cd server && .venv/bin/python -m pytest -q` and `cd web && npx vitest run`

Expected: both green.

- [ ] **Step 7: Re-run the secret sweep before anything is pushed public**

**Do NOT write the search terms into this file, a script, or a commit message.**
Enumerating the private strings in order to grep for them puts every one of
them in the repository — the check becomes the breach. (That is not
hypothetical: an earlier draft of this step did exactly that.)

Instead, keep the terms in a file outside the repository and read them in:

```bash
# ~/xxvi-private-terms.txt lives OUTSIDE the repo, one term per line:
# the recipient's and any third parties' names, both account passwords,
# the deployment hostname and server username, and any question answer.
while read -r t; do
  [ -z "$t" ] && continue
  n=$(git grep -I -l -- "$t" $(git rev-list --all) 2>/dev/null | wc -l)
  [ "$n" -gt 0 ] && echo "LEAK: a private term appears in $n object(s)"
done < ~/xxvi-private-terms.txt
```

Note the output names no term. Expected: no `LEAK:` lines at all. **If any
appear, STOP and report it — do not push.**

- [ ] **Step 8: Commit**

```bash
git add README.md web/public/audio/PROVENANCE.md .env.example
git commit -m "docs: README, asset provenance, and an .env example for N rewards"
```

---

## Notes for the executor

- **Tasks 4 and 5 are the risky ones.** They touch the vault and the gates — the two subsystems whose invariants protect the actual gift. Run the Postgres integration tests (`tests/integration/`) against a real database before considering either done, not just the SQLite unit tests.
- **Three steps say "verify, don't assume":** the 48-character label (6.5), the Simon flash reproduction (10.3), and the README quickstart (12.5). These exist because the spec author could not settle them from reading code. Report what you actually observed, including "I could not reproduce it".
- **`config/run.yaml` is gitignored and holds private content.** Never commit it, never quote it in a commit message, never screenshot it.

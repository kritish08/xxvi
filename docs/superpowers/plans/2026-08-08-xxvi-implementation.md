# XXVI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A desktop web experience disguised as a game console, where clearing eight game-plus-question segments releases two real PSN gift card codes.

**Architecture:** Modular-monolith FastAPI backend where a pure, exhaustively-tested state machine (`core/`) owns all progression truth, an isolated `vault/` owns code custody, and the React client is a renderer with no authority. Progress advances only through server-issued, single-use segment tokens. A WebSocket hub streams run state to an operator dashboard that must approve every code release.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x + asyncpg, Alembic, Pydantic v2, argon2-cffi, itsdangerous, pytest + pytest-asyncio. React 18 + Vite + TypeScript, Vitest. Neon Postgres. Docker Compose + Caddy.

## Global Constraints

Copied verbatim from the spec. Every task's requirements implicitly include this section.

- **Go-live: 20 Aug 2026, 00:00 IST.** Fixed. Stored as a UTC instant, rendered in `Asia/Kolkata`. The client's clock is never consulted or trusted.
- **The page must never be the only path to the gift.** Every gate has an operator override.
- **Codes live in env secrets** — never in the bundle, never in the database, never in logs or error traces.
- **No gift card code is ever emitted without explicit operator approval.**
- **One-time release is enforced by a DB unique constraint** — `UNIQUE (run_id, reward_id)` — at the database level, not in application logic.
- **Question answers never reach the client.** It receives prompts and choices; the correct index stays server-side.
- **Devil wipes clear segment progress and segment trophies. Code releases are never revoked.** Hidden trophies, once popped, stay popped.
- **"Restart current segment" means the whole segment** — game and question both, from the top.
- **The activation gate is rate-limited but never hard-locked.** Checkpoint gates lock after 3 attempts.
- **Keyboard is the supported input path.** Gamepad and fullscreen are enhancements that must never be required.
- **Every trophy pop must read as complete with the sound muted.**
- **The title `XXVI` is never explained anywhere in the product.**
- **Desktop only.** Landscape, high contrast, large type — it is viewed through Discord's lossy video codec.
- **Personal content lives only in `config/run.yaml`, which is gitignored.** Never commit questions, trophy names, the riddle, or the closing message.

## File Structure

```
server/
├── pyproject.toml
├── alembic.ini
├── alembic/versions/
├── xxvi/
│   ├── settings.py          env + secrets (pydantic-settings)
│   ├── main.py              app factory, health, router mounting
│   ├── content/
│   │   ├── schema.py        Pydantic models for run.yaml
│   │   └── loader.py        load + validate + cache
│   ├── core/
│   │   ├── models.py        Difficulty, Phase, Event, RunState
│   │   ├── machine.py       advance() — pure, zero I/O
│   │   └── trophies.py      award rules, platinum predicate
│   ├── games/
│   │   ├── seeds.py         seed → deterministic sequence
│   │   ├── verify.py        per-mechanic verification
│   │   └── tokens.py        signed single-use segment tokens
│   ├── auth/
│   │   ├── passwords.py     argon2 hash/verify
│   │   ├── sessions.py      signed session cookies
│   │   └── golive.py        the timed unlock + force override
│   ├── gates/service.py     hashed codes, attempts, lockout
│   ├── vault/service.py     one-time, operator-approved release
│   ├── persistence/
│   │   ├── models.py        SQLAlchemy tables
│   │   ├── session.py       engine + session factory
│   │   └── repositories.py  data access
│   ├── realtime/
│   │   ├── messages.py      WS discriminated unions
│   │   └── hub.py           connection registry + fan-out
│   ├── api/
│   │   ├── deps.py          auth/role/go-live dependencies
│   │   ├── auth_routes.py
│   │   ├── run_routes.py
│   │   ├── operator_routes.py
│   │   └── ws_routes.py
│   └── cli.py               dashboard-independent release path
└── tests/

web/
├── src/
│   ├── api.ts               GENERATED — do not edit
│   ├── ws-messages.ts       hand-written mirror of realtime/messages.py
│   ├── lib/{client,ws,fullscreen,input}.ts
│   ├── shell/               Boot, Activation, ProfileSelect, Difficulty,
│   │                        Install, HowToPlay, Question, Checkpoint,
│   │                        TrophyToast, TrophyCabinet
│   ├── games/               registry + SimonSays, SystemUpdate,
│   │                        StickDrift, TrophyRun
│   ├── ComingSoon.tsx, Operator.tsx, App.tsx
└── tests/

config/run.example.yaml      committed, placeholder content
config/run.yaml              GITIGNORED, the real thing
docker-compose.yml, Caddyfile, .env.example
```

**Cut order (spec §11.1).** Tasks are ordered so the never-cross line — boot → activation → 8 segments → checkpoint codes → code release — is complete by Task 20. Tasks 21–24 are the cuttable tail, in reverse cut priority.

---

## Task 1: Scaffold, settings, health endpoint

**Files:**
- Create: `server/pyproject.toml`, `server/xxvi/__init__.py`, `server/xxvi/settings.py`, `server/xxvi/main.py`
- Create: `server/tests/__init__.py`, `server/tests/test_health.py`
- Create: `.env.example`

**Interfaces:**
- Consumes: nothing
- Produces: `Settings` (pydantic-settings) with fields `database_url: str`, `session_secret: str`, `activation_code_hash: str`, `checkpoint_1_hash: str`, `checkpoint_2_hash: str`, `reward_1_code: str`, `reward_2_code: str`, `player_username: str`, `player_password_hash: str`, `operator_username: str`, `operator_password_hash: str`, `go_live_iso: str`, `dry_run: bool`. `get_settings() -> Settings` (lru_cached). `create_app() -> FastAPI`.

- [ ] **Step 1: Write `server/pyproject.toml`**

```toml
[project]
name = "xxvi"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.8",
    "pydantic-settings>=2.4",
    "sqlalchemy>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "argon2-cffi>=23.1",
    "itsdangerous>=2.2",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "httpx>=0.27"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.setuptools.packages.find]
include = ["xxvi*"]
```

- [ ] **Step 2: Write the failing test**

```python
# server/tests/test_health.py
from httpx import ASGITransport, AsyncClient

from xxvi.main import create_app


async def test_health_returns_ok():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 3: Run it and confirm it fails**

Run: `cd server && pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xxvi.main'`

- [ ] **Step 4: Write `server/xxvi/settings.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Write `server/xxvi/main.py`**

```python
from fastapi import APIRouter, FastAPI

health_router = APIRouter()


@health_router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def create_app() -> FastAPI:
    app = FastAPI(title="XXVI", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.include_router(health_router)
    return app


app = create_app()
```

- [ ] **Step 6: Run the test and confirm it passes**

Run: `cd server && pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 7: Write `.env.example`**

```bash
# Copy to .env and fill in. .env is gitignored and never committed.
DATABASE_URL=postgresql+asyncpg://user:pass@host/dbname
SESSION_SECRET=generate-with-openssl-rand-hex-32

# Hashes only. Generate with: python -m xxvi.cli hash-secret
ACTIVATION_CODE_HASH=
CHECKPOINT_1_HASH=
CHECKPOINT_2_HASH=

# Dummy values until the night of the 20th.
REWARD_1_CODE=DUMMY-REWARD-0001
REWARD_2_CODE=DUMMY-REWARD-0002

PLAYER_USERNAME=
PLAYER_PASSWORD_HASH=
OPERATOR_USERNAME=
OPERATOR_PASSWORD_HASH=

GO_LIVE_ISO=2026-08-20T00:00:00+05:30
DRY_RUN=false
```

- [ ] **Step 8: Commit**

```bash
git add server .env.example
git commit -m "feat: scaffold FastAPI app with settings and health endpoint"
```

---

## Task 2: Content schema and loader

**Files:**
- Create: `server/xxvi/content/__init__.py`, `server/xxvi/content/schema.py`, `server/xxvi/content/loader.py`
- Create: `config/run.example.yaml`
- Test: `server/tests/test_content.py`

**Interfaces:**
- Consumes: nothing
- Produces: `RunConfig` with `.recipient: str`, `.acts: int`, `.segments_per_act: int`, `.total_segments: int` (property), `.questions: list[Question]`, `.games: list[GameSlot]`, `.trophies: list[Trophy]`, `.rewards: list[Reward]`, `.copy: CopyBlock`. `Question` has `.prompt`, `.choices: list[str]`, `.answer: int`, `.roast: str`. `GameSlot` has `.segment: int`, `.mechanic: str`, `.params: dict`. `Trophy` has `.id`, `.name`, `.grade`, `.hidden: bool`. `Reward` has `.id: int`, `.after_act: int`, `.label: str`. `load_config(path: Path) -> RunConfig`.

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_content.py
from pathlib import Path

import pytest
from pydantic import ValidationError

from xxvi.content.loader import load_config

EXAMPLE = Path(__file__).parents[2] / "config" / "run.example.yaml"


def test_example_config_loads():
    config = load_config(EXAMPLE)
    assert config.total_segments == 8
    assert len(config.questions) == 8
    assert len(config.games) == 8
    assert len(config.rewards) == 2


def test_question_count_must_match_total_segments(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "recipient: X\nacts: 2\nsegments_per_act: 4\n"
        "questions: []\ngames: []\ntrophies: []\nrewards: []\n"
        "copy: {coming_soon: a, teaser: b, how_to_play: c, closing: d}\n"
    )
    with pytest.raises(ValidationError, match="questions"):
        load_config(bad)


def test_answer_index_must_be_within_choices(tmp_path):
    from xxvi.content.schema import Question

    with pytest.raises(ValidationError, match="answer"):
        Question(prompt="p", choices=["a", "b"], answer=5, roast="r")
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd server && pytest tests/test_content.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xxvi.content'`

- [ ] **Step 3: Write `server/xxvi/content/schema.py`**

```python
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

Mechanic = Literal["simon", "update", "drift", "trophy_run"]
Grade = Literal["bronze", "silver", "gold", "platinum"]


class Question(BaseModel):
    prompt: str
    choices: list[str] = Field(min_length=2, max_length=4)
    answer: int
    roast: str

    @model_validator(mode="after")
    def answer_within_choices(self) -> Self:
        if not 0 <= self.answer < len(self.choices):
            raise ValueError(f"answer {self.answer} is outside choices")
        return self


class GameSlot(BaseModel):
    segment: int = Field(ge=1)
    mechanic: Mechanic
    params: dict[str, float | int] = Field(default_factory=dict)


class Trophy(BaseModel):
    id: str
    name: str
    grade: Grade
    hidden: bool = False


class Reward(BaseModel):
    id: int = Field(ge=1)
    after_act: int = Field(ge=1)
    label: str


class CopyBlock(BaseModel):
    coming_soon: str
    teaser: str
    how_to_play: str
    closing: str


class RunConfig(BaseModel):
    recipient: str
    acts: int = Field(ge=1)
    segments_per_act: int = Field(ge=1)
    questions: list[Question]
    games: list[GameSlot]
    trophies: list[Trophy]
    rewards: list[Reward]
    copy: CopyBlock

    @property
    def total_segments(self) -> int:
        return self.acts * self.segments_per_act

    @model_validator(mode="after")
    def counts_line_up(self) -> Self:
        total = self.acts * self.segments_per_act
        if len(self.questions) != total:
            raise ValueError(f"questions: expected {total}, got {len(self.questions)}")
        if len(self.games) != total:
            raise ValueError(f"games: expected {total}, got {len(self.games)}")
        if {g.segment for g in self.games} != set(range(1, total + 1)):
            raise ValueError(f"games: segments must cover 1..{total} exactly once")
        if len(self.rewards) != self.acts:
            raise ValueError(f"rewards: expected {self.acts}, got {len(self.rewards)}")
        return self
```

- [ ] **Step 4: Write `server/xxvi/content/loader.py`**

```python
from functools import lru_cache
from pathlib import Path

import yaml

from xxvi.content.schema import RunConfig

DEFAULT_PATH = Path("config/run.yaml")


def load_config(path: Path = DEFAULT_PATH) -> RunConfig:
    raw = yaml.safe_load(path.read_text())
    return RunConfig.model_validate(raw)


@lru_cache
def get_config() -> RunConfig:
    path = DEFAULT_PATH if DEFAULT_PATH.exists() else Path("config/run.example.yaml")
    return load_config(path)
```

- [ ] **Step 5: Write `config/run.example.yaml`**

Placeholder content only. The real file is `config/run.yaml` and is gitignored.

```yaml
recipient: "PLACEHOLDER"
acts: 2
segments_per_act: 4

questions:
  - { prompt: "Q1 placeholder", choices: ["a", "b", "c", "d"], answer: 0, roast: "roast placeholder" }
  - { prompt: "Q2 placeholder", choices: ["a", "b", "c", "d"], answer: 1, roast: "roast placeholder" }
  - { prompt: "Q3 placeholder", choices: ["a", "b", "c", "d"], answer: 2, roast: "roast placeholder" }
  - { prompt: "Q4 placeholder", choices: ["a", "b", "c", "d"], answer: 3, roast: "roast placeholder" }
  - { prompt: "Q5 placeholder", choices: ["a", "b", "c", "d"], answer: 0, roast: "roast placeholder" }
  - { prompt: "Q6 placeholder", choices: ["a", "b", "c", "d"], answer: 1, roast: "roast placeholder" }
  - { prompt: "Q7 placeholder", choices: ["a", "b", "c", "d"], answer: 2, roast: "roast placeholder" }
  - { prompt: "Q8 placeholder", choices: ["a", "b", "c", "d"], answer: 3, roast: "roast placeholder" }

games:
  - { segment: 1, mechanic: simon,      params: { length: 4 } }
  - { segment: 2, mechanic: update,     params: { taps_required: 20 } }
  - { segment: 3, mechanic: drift,      params: { duration_ms: 20000, drift_rate: 1.0 } }
  - { segment: 4, mechanic: trophy_run, params: { prompts: 6, window_ms: 1200 } }
  - { segment: 5, mechanic: simon,      params: { length: 7 } }
  - { segment: 6, mechanic: update,     params: { taps_required: 35 } }
  - { segment: 7, mechanic: drift,      params: { duration_ms: 25000, drift_rate: 1.8 } }
  - { segment: 8, mechanic: trophy_run, params: { prompts: 10, window_ms: 800 } }

trophies:
  - { id: "game-1",  name: "Trophy placeholder",  grade: bronze }
  - { id: "game-2",  name: "Trophy placeholder",  grade: bronze }
  - { id: "game-3",  name: "Trophy placeholder",  grade: bronze }
  - { id: "game-4",  name: "Trophy placeholder",  grade: bronze }
  - { id: "game-5",  name: "Trophy placeholder",  grade: silver }
  - { id: "game-6",  name: "Trophy placeholder",  grade: silver }
  - { id: "game-7",  name: "Trophy placeholder",  grade: silver }
  - { id: "game-8",  name: "Trophy placeholder",  grade: silver }
  - { id: "question-1", name: "Trophy placeholder", grade: bronze }
  - { id: "question-2", name: "Trophy placeholder", grade: bronze }
  - { id: "question-3", name: "Trophy placeholder", grade: bronze }
  - { id: "question-4", name: "Trophy placeholder", grade: bronze }
  - { id: "question-5", name: "Trophy placeholder", grade: bronze }
  - { id: "question-6", name: "Trophy placeholder", grade: bronze }
  - { id: "question-7", name: "Trophy placeholder", grade: bronze }
  - { id: "question-8", name: "Trophy placeholder", grade: bronze }
  - { id: "act-1",   name: "Trophy placeholder", grade: gold }
  - { id: "act-2",   name: "Trophy placeholder", grade: gold }
  - { id: "platinum", name: "Trophy placeholder", grade: platinum }
  - { id: "hidden-rage-quit",    name: "???", grade: bronze, hidden: true }
  - { id: "hidden-drift-denier", name: "???", grade: bronze, hidden: true }
  - { id: "hidden-speedrun",     name: "???", grade: silver, hidden: true }

rewards:
  - { id: 1, after_act: 1, label: "Reward placeholder" }
  - { id: 2, after_act: 2, label: "Reward placeholder" }

copy:
  coming_soon: "placeholder"
  teaser: "placeholder"
  how_to_play: "placeholder"
  closing: "placeholder"
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `cd server && pytest tests/test_content.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add server/xxvi/content server/tests/test_content.py config/run.example.yaml
git commit -m "feat: add validated YAML content schema and loader"
```

---

## Task 3: Core state machine

This is the module that must be correct at midnight. Pure functions, zero I/O, exhaustive tests.

**Files:**
- Create: `server/xxvi/core/__init__.py`, `server/xxvi/core/models.py`, `server/xxvi/core/machine.py`
- Test: `server/tests/test_core_machine.py`

**Interfaces:**
- Consumes: nothing (deliberately — `core/` imports no other project module)
- Produces: `Difficulty` (`KIDDIE`, `DEVIL`), `Phase` (`ACTIVATION`, `PROFILE`, `DIFFICULTY`, `INSTALL`, `HOWTO`, `GAME`, `QUESTION`, `CHECKPOINT`, `COMPLETE`), `Event` (`ACTIVATED`, `PROFILE_CHOSEN`, `DIFFICULTY_CHOSEN`, `INSTALLED`, `HOWTO_ACKED`, `GAME_PASSED`, `GAME_FAILED`, `QUESTION_PASSED`, `QUESTION_FAILED`, `CHECKPOINT_PASSED`), frozen dataclass `RunState(phase, difficulty, segment, cleared_segments, released_rewards)`, `Shape(acts, segments_per_act)` with `.total`, `initial_state() -> RunState`, `advance(state, event, shape) -> RunState`, and `act_of(segment, shape) -> int`.

- [ ] **Step 1: Write `server/xxvi/core/models.py`**

```python
from dataclasses import dataclass, replace
from enum import StrEnum


class Difficulty(StrEnum):
    KIDDIE = "kiddie"
    DEVIL = "devil"


class Phase(StrEnum):
    ACTIVATION = "activation"
    PROFILE = "profile"
    DIFFICULTY = "difficulty"
    INSTALL = "install"
    HOWTO = "howto"
    GAME = "game"
    QUESTION = "question"
    CHECKPOINT = "checkpoint"
    COMPLETE = "complete"


class Event(StrEnum):
    ACTIVATED = "activated"
    PROFILE_CHOSEN = "profile_chosen"
    DIFFICULTY_CHOSEN = "difficulty_chosen"
    INSTALLED = "installed"
    HOWTO_ACKED = "howto_acked"
    GAME_PASSED = "game_passed"
    GAME_FAILED = "game_failed"
    QUESTION_PASSED = "question_passed"
    QUESTION_FAILED = "question_failed"
    CHECKPOINT_PASSED = "checkpoint_passed"


@dataclass(frozen=True)
class Shape:
    acts: int = 2
    segments_per_act: int = 4

    @property
    def total(self) -> int:
        return self.acts * self.segments_per_act


@dataclass(frozen=True)
class RunState:
    phase: Phase = Phase.ACTIVATION
    difficulty: Difficulty | None = None
    segment: int = 0
    cleared_segments: frozenset[int] = frozenset()
    released_rewards: frozenset[int] = frozenset()

    def with_(self, **changes: object) -> "RunState":
        return replace(self, **changes)  # type: ignore[arg-type]


def initial_state() -> RunState:
    return RunState()


def act_of(segment: int, shape: Shape) -> int:
    return (segment - 1) // shape.segments_per_act + 1
```

- [ ] **Step 2: Write the failing tests**

```python
# server/tests/test_core_machine.py
import pytest

from xxvi.core.machine import InvalidTransition, advance
from xxvi.core.models import Difficulty, Event, Phase, RunState, Shape, initial_state

SHAPE = Shape(acts=2, segments_per_act=4)


def at_segment(n: int, phase: Phase, difficulty: Difficulty, cleared=frozenset(), released=frozenset()):
    return RunState(phase=phase, difficulty=difficulty, segment=n,
                    cleared_segments=cleared, released_rewards=released)


def test_preamble_walks_activation_to_first_game():
    state = initial_state()
    for event in (Event.ACTIVATED, Event.PROFILE_CHOSEN):
        state = advance(state, event, SHAPE)
    assert state.phase is Phase.DIFFICULTY

    state = advance(state, Event.DIFFICULTY_CHOSEN, SHAPE, difficulty=Difficulty.DEVIL)
    assert state.difficulty is Difficulty.DEVIL

    state = advance(state, Event.INSTALLED, SHAPE)
    state = advance(state, Event.HOWTO_ACKED, SHAPE)
    assert state.phase is Phase.GAME
    assert state.segment == 1


def test_game_pass_moves_to_question_same_segment():
    state = at_segment(3, Phase.GAME, Difficulty.KIDDIE)
    result = advance(state, Event.GAME_PASSED, SHAPE)
    assert result.phase is Phase.QUESTION
    assert result.segment == 3


def test_question_pass_clears_segment_and_advances():
    state = at_segment(2, Phase.QUESTION, Difficulty.KIDDIE, cleared=frozenset({1}))
    result = advance(state, Event.QUESTION_PASSED, SHAPE)
    assert result.cleared_segments == frozenset({1, 2})
    assert result.segment == 3
    assert result.phase is Phase.GAME


def test_last_segment_of_act_leads_to_checkpoint():
    state = at_segment(4, Phase.QUESTION, Difficulty.KIDDIE, cleared=frozenset({1, 2, 3}))
    result = advance(state, Event.QUESTION_PASSED, SHAPE)
    assert result.phase is Phase.CHECKPOINT
    assert result.segment == 4


def test_checkpoint_releases_reward_and_opens_next_act():
    state = at_segment(4, Phase.CHECKPOINT, Difficulty.KIDDIE, cleared=frozenset({1, 2, 3, 4}))
    result = advance(state, Event.CHECKPOINT_PASSED, SHAPE)
    assert result.released_rewards == frozenset({1})
    assert result.segment == 5
    assert result.phase is Phase.GAME


def test_final_checkpoint_completes_the_run():
    state = at_segment(8, Phase.CHECKPOINT, Difficulty.DEVIL,
                       cleared=frozenset(range(1, 9)), released=frozenset({1}))
    result = advance(state, Event.CHECKPOINT_PASSED, SHAPE)
    assert result.phase is Phase.COMPLETE
    assert result.released_rewards == frozenset({1, 2})


@pytest.mark.parametrize("failure", [Event.GAME_FAILED, Event.QUESTION_FAILED])
@pytest.mark.parametrize("segment", range(1, 9))
def test_kiddie_failure_restarts_only_the_current_segment(segment, failure):
    cleared = frozenset(range(1, segment))
    released = frozenset({1}) if segment > 4 else frozenset()
    phase = Phase.GAME if failure is Event.GAME_FAILED else Phase.QUESTION
    state = at_segment(segment, phase, Difficulty.KIDDIE, cleared=cleared, released=released)

    result = advance(state, failure, SHAPE)

    assert result.segment == segment
    assert result.phase is Phase.GAME, "restart means the whole segment, game first"
    assert result.cleared_segments == cleared
    assert result.released_rewards == released


@pytest.mark.parametrize("failure", [Event.GAME_FAILED, Event.QUESTION_FAILED])
@pytest.mark.parametrize("segment", range(1, 9))
def test_devil_failure_wipes_progress_but_never_rewards(segment, failure):
    cleared = frozenset(range(1, segment))
    released = frozenset({1}) if segment > 4 else frozenset()
    phase = Phase.GAME if failure is Event.GAME_FAILED else Phase.QUESTION
    state = at_segment(segment, phase, Difficulty.DEVIL, cleared=cleared, released=released)

    result = advance(state, failure, SHAPE)

    assert result.segment == 1
    assert result.phase is Phase.GAME
    assert result.cleared_segments == frozenset()
    assert result.released_rewards == released, "earned codes are never revoked"


def test_devil_wipe_in_act_two_keeps_reward_one():
    state = at_segment(7, Phase.GAME, Difficulty.DEVIL,
                       cleared=frozenset({1, 2, 3, 4, 5, 6}), released=frozenset({1}))
    result = advance(state, Event.GAME_FAILED, SHAPE)
    assert result.released_rewards == frozenset({1})
    assert result.segment == 1


def test_events_out_of_phase_are_rejected():
    state = at_segment(1, Phase.GAME, Difficulty.KIDDIE)
    with pytest.raises(InvalidTransition):
        advance(state, Event.CHECKPOINT_PASSED, SHAPE)


def test_advance_never_mutates_the_input_state():
    state = at_segment(2, Phase.QUESTION, Difficulty.DEVIL, cleared=frozenset({1}))
    advance(state, Event.QUESTION_FAILED, SHAPE)
    assert state.segment == 2
    assert state.cleared_segments == frozenset({1})
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `cd server && pytest tests/test_core_machine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xxvi.core.machine'`

- [ ] **Step 4: Write `server/xxvi/core/machine.py`**

```python
from xxvi.core.models import Difficulty, Event, Phase, RunState, Shape, act_of


class InvalidTransition(Exception):
    """An event arrived that the current phase does not accept."""


_PREAMBLE: dict[Phase, tuple[Event, Phase]] = {
    Phase.ACTIVATION: (Event.ACTIVATED, Phase.PROFILE),
    Phase.PROFILE: (Event.PROFILE_CHOSEN, Phase.DIFFICULTY),
    Phase.DIFFICULTY: (Event.DIFFICULTY_CHOSEN, Phase.INSTALL),
    Phase.INSTALL: (Event.INSTALLED, Phase.HOWTO),
}

_FAILURES = {Event.GAME_FAILED, Event.QUESTION_FAILED}


def advance(
    state: RunState,
    event: Event,
    shape: Shape,
    *,
    difficulty: Difficulty | None = None,
) -> RunState:
    if state.phase in _PREAMBLE:
        expected, next_phase = _PREAMBLE[state.phase]
        if event is not expected:
            raise InvalidTransition(f"{state.phase} does not accept {event}")
        if event is Event.DIFFICULTY_CHOSEN:
            if difficulty is None:
                raise InvalidTransition("DIFFICULTY_CHOSEN requires a difficulty")
            return state.with_(phase=next_phase, difficulty=difficulty)
        return state.with_(phase=next_phase)

    if state.phase is Phase.HOWTO:
        if event is not Event.HOWTO_ACKED:
            raise InvalidTransition(f"{state.phase} does not accept {event}")
        return state.with_(phase=Phase.GAME, segment=1)

    if event in _FAILURES:
        if state.phase not in (Phase.GAME, Phase.QUESTION):
            raise InvalidTransition(f"{state.phase} does not accept {event}")
        return _apply_failure(state)

    if state.phase is Phase.GAME:
        if event is not Event.GAME_PASSED:
            raise InvalidTransition(f"{state.phase} does not accept {event}")
        return state.with_(phase=Phase.QUESTION)

    if state.phase is Phase.QUESTION:
        if event is not Event.QUESTION_PASSED:
            raise InvalidTransition(f"{state.phase} does not accept {event}")
        return _clear_segment(state, shape)

    if state.phase is Phase.CHECKPOINT:
        if event is not Event.CHECKPOINT_PASSED:
            raise InvalidTransition(f"{state.phase} does not accept {event}")
        return _pass_checkpoint(state, shape)

    raise InvalidTransition(f"{state.phase} is terminal and accepts nothing")


def _apply_failure(state: RunState) -> RunState:
    # Restart means the whole segment, game first — never the question alone.
    if state.difficulty is Difficulty.KIDDIE:
        return state.with_(phase=Phase.GAME)
    # Devil clears segment progress. Released rewards are never revoked.
    return state.with_(phase=Phase.GAME, segment=1, cleared_segments=frozenset())


def _clear_segment(state: RunState, shape: Shape) -> RunState:
    cleared = state.cleared_segments | {state.segment}
    at_act_boundary = state.segment % shape.segments_per_act == 0
    if at_act_boundary:
        return state.with_(phase=Phase.CHECKPOINT, cleared_segments=cleared)
    return state.with_(phase=Phase.GAME, segment=state.segment + 1, cleared_segments=cleared)


def _pass_checkpoint(state: RunState, shape: Shape) -> RunState:
    act = act_of(state.segment, shape)
    released = state.released_rewards | {act}
    if act >= shape.acts:
        return state.with_(phase=Phase.COMPLETE, released_rewards=released)
    return state.with_(
        phase=Phase.GAME,
        segment=state.segment + 1,
        released_rewards=released,
    )
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd server && pytest tests/test_core_machine.py -v`
Expected: PASS — 39 tests (the two parametrized failure tests generate 16 each)

- [ ] **Step 6: Commit**

```bash
git add server/xxvi/core server/tests/test_core_machine.py
git commit -m "feat: add pure run state machine with exhaustive wipe-rule tests"
```

---

## Task 4: Trophy award rules

**Files:**
- Create: `server/xxvi/core/trophies.py`
- Test: `server/tests/test_core_trophies.py`

**Interfaces:**
- Consumes: `Event`, `Phase`, `RunState`, `Shape`, `act_of` from Task 3
- Produces: `trophy_for(state_before, event, shape) -> str | None`, `PLATINUM_ID = "platinum"`, `required_for_platinum(shape) -> frozenset[str]`, `platinum_earned(earned, shape) -> bool`, `wipe_trophies(earned) -> frozenset[str]`

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/test_core_trophies.py
from xxvi.core.models import Difficulty, Event, Phase, RunState, Shape
from xxvi.core.trophies import (
    PLATINUM_ID,
    platinum_earned,
    required_for_platinum,
    trophy_for,
    wipe_trophies,
)

SHAPE = Shape(acts=2, segments_per_act=4)


def state(segment: int, phase: Phase) -> RunState:
    return RunState(phase=phase, difficulty=Difficulty.KIDDIE, segment=segment)


def test_passing_a_game_awards_that_segments_game_trophy():
    assert trophy_for(state(3, Phase.GAME), Event.GAME_PASSED, SHAPE) == "game-3"


def test_passing_a_question_awards_that_segments_question_trophy():
    assert trophy_for(state(6, Phase.QUESTION), Event.QUESTION_PASSED, SHAPE) == "question-6"


def test_passing_a_checkpoint_awards_the_act_trophy():
    assert trophy_for(state(8, Phase.CHECKPOINT), Event.CHECKPOINT_PASSED, SHAPE) == "act-2"


def test_failures_award_nothing():
    assert trophy_for(state(3, Phase.GAME), Event.GAME_FAILED, SHAPE) is None


def test_platinum_requires_all_eighteen_others():
    required = required_for_platinum(SHAPE)
    assert len(required) == 18
    assert PLATINUM_ID not in required
    assert not platinum_earned(required - {"question-8"}, SHAPE)
    assert platinum_earned(required, SHAPE)


def test_hidden_trophies_do_not_gate_the_platinum():
    earned = required_for_platinum(SHAPE) | {"hidden-rage-quit"}
    assert platinum_earned(earned, SHAPE)


def test_a_wipe_clears_segment_trophies_but_keeps_hidden_ones():
    earned = frozenset({"game-1", "question-1", "act-1", "hidden-rage-quit"})
    assert wipe_trophies(earned) == frozenset({"hidden-rage-quit"})
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd server && pytest tests/test_core_trophies.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xxvi.core.trophies'`

- [ ] **Step 3: Write `server/xxvi/core/trophies.py`**

```python
from collections.abc import Iterable

from xxvi.core.models import Event, RunState, Shape, act_of

PLATINUM_ID = "platinum"
HIDDEN_PREFIX = "hidden-"


def trophy_for(state: RunState, event: Event, shape: Shape) -> str | None:
    """The trophy awarded by `event` given the state it was applied to."""
    match event:
        case Event.GAME_PASSED:
            return f"game-{state.segment}"
        case Event.QUESTION_PASSED:
            return f"question-{state.segment}"
        case Event.CHECKPOINT_PASSED:
            return f"act-{act_of(state.segment, shape)}"
        case _:
            return None


def required_for_platinum(shape: Shape) -> frozenset[str]:
    segments = range(1, shape.total + 1)
    acts = range(1, shape.acts + 1)
    return frozenset(
        [f"game-{n}" for n in segments]
        + [f"question-{n}" for n in segments]
        + [f"act-{a}" for a in acts]
    )


def platinum_earned(earned: Iterable[str], shape: Shape) -> bool:
    return required_for_platinum(shape) <= set(earned)


def wipe_trophies(earned: Iterable[str]) -> frozenset[str]:
    """A Devil wipe clears segment trophies. Hidden ones, once popped, stay popped."""
    return frozenset(t for t in earned if t.startswith(HIDDEN_PREFIX))
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd server && pytest tests/test_core_trophies.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add server/xxvi/core/trophies.py server/tests/test_core_trophies.py
git commit -m "feat: add trophy award rules and platinum predicate"
```

---

## Task 5: Persistence — tables, migration, repositories

**Files:**
- Create: `server/xxvi/persistence/__init__.py`, `server/xxvi/persistence/models.py`, `server/xxvi/persistence/session.py`, `server/xxvi/persistence/repositories.py`
- Create: `server/alembic.ini`, `server/alembic/env.py`, `server/alembic/versions/0001_initial.py`
- Test: `server/tests/test_persistence.py`, `server/tests/conftest.py`

**Interfaces:**
- Consumes: `Settings` (Task 1); `Difficulty`, `Phase`, `RunState` (Task 3)
- Produces: SQLAlchemy models `Account`, `Run`, `RunEvent`, `TrophyEarned`, `GateAttempt`, `CodeRelease`. `get_sessionmaker() -> async_sessionmaker`. `RunRepository` with `async get_by_account(account_id) -> Run | None`, `async create(account_id, difficulty) -> Run`, `async save_state(run_id, state: RunState) -> None`, `async append_event(run_id, kind: str, payload: dict) -> None`, `async has_event(run_id, kind, payload_match: dict) -> bool`, `async earned_trophies(run_id) -> frozenset[str]`, `async award_trophy(run_id, trophy_id) -> bool`, `async clear_segment_trophies(run_id) -> None`.

- [ ] **Step 1: Write `server/xxvi/persistence/models.py`**

```python
from datetime import datetime

from sqlalchemy import (
    JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16))  # "player" | "operator"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True)
    difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    phase: Mapped[str] = mapped_column(String(16))
    segment: Mapped[int] = mapped_column(Integer, default=0)
    cleared_segments: Mapped[list[int]] = mapped_column(JSON, default=list)
    released_rewards: Mapped[list[int]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RunEvent(Base):
    """Append-only. Drives the dashboard, the end-screen stats, and debugging."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(48), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrophyEarned(Base):
    __tablename__ = "trophies_earned"
    __table_args__ = (UniqueConstraint("run_id", "trophy_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    trophy_id: Mapped[str] = mapped_column(String(64))
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GateAttempt(Base):
    __tablename__ = "gate_attempts"
    __table_args__ = (UniqueConstraint("run_id", "gate_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    gate_id: Mapped[str] = mapped_column(String(32))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked: Mapped[bool] = mapped_column(default=False)


class CodeRelease(Base):
    """Records THAT a reward was released. Never its value."""

    __tablename__ = "code_releases"
    __table_args__ = (UniqueConstraint("run_id", "reward_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    reward_id: Mapped[int] = mapped_column(Integer)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 2: Write `server/xxvi/persistence/session.py`**

```python
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from xxvi.settings import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker:
    return async_sessionmaker(get_engine(), expire_on_commit=False)
```

- [ ] **Step 3: Write `server/tests/conftest.py`**

Tests run against SQLite in-memory so they need no Neon connection. The one place that matters — the `UNIQUE` constraint behaviour in Task 9 — is identical on both engines.

```python
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from xxvi.persistence.models import Account, Base


@pytest.fixture
async def sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def account(sessionmaker):
    async with sessionmaker() as session:
        row = Account(username="him", password_hash="x", role="player")
        session.add(row)
        await session.commit()
        return row
```

Add `aiosqlite>=0.20` to the `dev` extras in `pyproject.toml`.

- [ ] **Step 4: Write the failing tests**

```python
# server/tests/test_persistence.py
from xxvi.core.models import Difficulty, Phase, RunState
from xxvi.persistence.repositories import RunRepository


async def test_create_and_reload_a_run(sessionmaker, account):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.DEVIL)
    reloaded = await repo.get_by_account(account.id)
    assert reloaded is not None
    assert reloaded.id == run.id
    assert reloaded.difficulty == "devil"


async def test_save_state_round_trips(sessionmaker, account):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    state = RunState(
        phase=Phase.QUESTION, difficulty=Difficulty.KIDDIE, segment=5,
        cleared_segments=frozenset({1, 2, 3, 4}), released_rewards=frozenset({1}),
    )
    await repo.save_state(run.id, state)

    reloaded = await repo.get_by_account(account.id)
    assert reloaded.phase == "question"
    assert reloaded.segment == 5
    assert sorted(reloaded.cleared_segments) == [1, 2, 3, 4]
    assert reloaded.released_rewards == [1]


async def test_awarding_a_trophy_twice_is_idempotent(sessionmaker, account):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    assert await repo.award_trophy(run.id, "game-1") is True
    assert await repo.award_trophy(run.id, "game-1") is False
    assert await repo.earned_trophies(run.id) == frozenset({"game-1"})


async def test_clearing_segment_trophies_keeps_hidden_ones(sessionmaker, account):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.DEVIL)
    for trophy in ("game-1", "question-1", "act-1", "hidden-rage-quit"):
        await repo.award_trophy(run.id, trophy)

    await repo.clear_segment_trophies(run.id)
    assert await repo.earned_trophies(run.id) == frozenset({"hidden-rage-quit"})


async def test_events_are_appended_and_searchable(sessionmaker, account):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    await repo.append_event(run.id, "token_consumed", {"nonce": "abc"})

    assert await repo.has_event(run.id, "token_consumed", {"nonce": "abc"}) is True
    assert await repo.has_event(run.id, "token_consumed", {"nonce": "zzz"}) is False
```

- [ ] **Step 5: Run them and confirm they fail**

Run: `cd server && pytest tests/test_persistence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xxvi.persistence.repositories'`

- [ ] **Step 6: Write `server/xxvi/persistence/repositories.py`**

```python
from sqlalchemy import delete, not_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from xxvi.core.models import Difficulty, RunState
from xxvi.core.trophies import HIDDEN_PREFIX
from xxvi.persistence.models import Run, RunEvent, TrophyEarned


class RunRepository:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def create(self, account_id: int, difficulty: Difficulty | None) -> Run:
        async with self._sessionmaker() as session:
            run = Run(
                account_id=account_id,
                difficulty=difficulty.value if difficulty else None,
                phase="activation",
                segment=0,
                cleared_segments=[],
                released_rewards=[],
            )
            session.add(run)
            await session.commit()
            return run

    async def get_by_account(self, account_id: int) -> Run | None:
        async with self._sessionmaker() as session:
            result = await session.execute(select(Run).where(Run.account_id == account_id))
            return result.scalar_one_or_none()

    async def save_state(self, run_id: int, state: RunState) -> None:
        async with self._sessionmaker() as session:
            run = await session.get(Run, run_id)
            run.phase = state.phase.value
            run.difficulty = state.difficulty.value if state.difficulty else None
            run.segment = state.segment
            run.cleared_segments = sorted(state.cleared_segments)
            run.released_rewards = sorted(state.released_rewards)
            await session.commit()

    async def append_event(self, run_id: int, kind: str, payload: dict) -> None:
        async with self._sessionmaker() as session:
            session.add(RunEvent(run_id=run_id, kind=kind, payload=payload))
            await session.commit()

    async def has_event(self, run_id: int, kind: str, payload_match: dict) -> bool:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.kind == kind)
            )
            return any(
                all(row.payload.get(k) == v for k, v in payload_match.items())
                for row in result.scalars()
            )

    async def earned_trophies(self, run_id: int) -> frozenset[str]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(TrophyEarned.trophy_id).where(TrophyEarned.run_id == run_id)
            )
            return frozenset(result.scalars())

    async def award_trophy(self, run_id: int, trophy_id: str) -> bool:
        """Returns True if newly awarded, False if already held."""
        async with self._sessionmaker() as session:
            session.add(TrophyEarned(run_id=run_id, trophy_id=trophy_id))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False
            return True

    async def clear_segment_trophies(self, run_id: int) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                delete(TrophyEarned).where(
                    TrophyEarned.run_id == run_id,
                    not_(TrophyEarned.trophy_id.startswith(HIDDEN_PREFIX)),
                )
            )
            await session.commit()
```

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `cd server && pytest tests/test_persistence.py -v`
Expected: PASS (5 tests)

- [ ] **Step 8: Generate the Alembic migration**

```bash
cd server
alembic init -t async alembic   # then point alembic/env.py at Base.metadata
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

In `alembic/env.py`, replace the `target_metadata = None` line with:

```python
from xxvi.persistence.models import Base
from xxvi.settings import get_settings

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", get_settings().database_url)
```

- [ ] **Step 9: Commit**

```bash
git add server/xxvi/persistence server/tests/test_persistence.py \
        server/tests/conftest.py server/alembic server/alembic.ini
git commit -m "feat: add persistence layer with run, trophy and event repositories"
```

---

## Task 6: Auth, sessions, and the timed unlock

**Files:**
- Create: `server/xxvi/auth/__init__.py`, `server/xxvi/auth/passwords.py`, `server/xxvi/auth/sessions.py`, `server/xxvi/auth/golive.py`
- Test: `server/tests/test_auth.py`, `server/tests/test_golive.py`

**Interfaces:**
- Consumes: `Settings` (Task 1)
- Produces: `hash_password(plain) -> str`, `verify_password(plain, hashed) -> bool`; `SessionData(account_id: int, role: str)`, `issue_session(data) -> str`, `read_session(token) -> SessionData | None`; `go_live_instant(settings) -> datetime` (UTC-aware), `is_live(now, settings, *, forced: bool) -> bool`, `seconds_until_live(now, settings) -> int`.

- [ ] **Step 1: Write the failing tests for passwords and sessions**

```python
# server/tests/test_auth.py
from xxvi.auth.passwords import hash_password, verify_password
from xxvi.auth.sessions import SessionData, issue_session, read_session


def test_password_round_trips_and_rejects_wrong_input():
    hashed = hash_password("correct horse")
    assert verify_password("correct horse", hashed) is True
    assert verify_password("wrong horse", hashed) is False


def test_hash_is_salted_so_two_hashes_of_one_password_differ():
    assert hash_password("same") != hash_password("same")


def test_session_round_trips():
    token = issue_session(SessionData(account_id=7, role="player"))
    restored = read_session(token)
    assert restored == SessionData(account_id=7, role="player")


def test_tampered_session_is_rejected():
    token = issue_session(SessionData(account_id=7, role="player"))
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    assert read_session(tampered) is None


def test_garbage_session_is_rejected_without_raising():
    assert read_session("not-a-token") is None
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd server && pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xxvi.auth'`

- [ ] **Step 3: Write `server/xxvi/auth/passwords.py`**

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError):
        return False
```

- [ ] **Step 4: Write `server/xxvi/auth/sessions.py`**

```python
from dataclasses import asdict, dataclass

from itsdangerous import BadSignature, URLSafeSerializer

from xxvi.settings import get_settings

SESSION_COOKIE = "xxvi_session"
_SALT = "xxvi.session.v1"


@dataclass(frozen=True)
class SessionData:
    account_id: int
    role: str


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().session_secret, salt=_SALT)


def issue_session(data: SessionData) -> str:
    return _serializer().dumps(asdict(data))


def read_session(token: str) -> SessionData | None:
    try:
        payload = _serializer().loads(token)
    except BadSignature:
        return None
    try:
        return SessionData(account_id=int(payload["account_id"]), role=str(payload["role"]))
    except (KeyError, TypeError, ValueError):
        return None
```

- [ ] **Step 5: Run the auth tests and confirm they pass**

Run: `cd server && pytest tests/test_auth.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Write the failing tests for the timed unlock**

The likeliest bug in the build, so it gets its own explicit assertions.

```python
# server/tests/test_golive.py
from datetime import UTC, datetime, timedelta

from xxvi.auth.golive import go_live_instant, is_live, seconds_until_live
from xxvi.settings import Settings

SETTINGS = Settings(go_live_iso="2026-08-20T00:00:00+05:30")


def test_ist_midnight_resolves_to_the_expected_utc_instant():
    # 00:00 on 20 Aug in Asia/Kolkata is 18:30 on 19 Aug UTC.
    assert go_live_instant(SETTINGS) == datetime(2026, 8, 19, 18, 30, tzinfo=UTC)


def test_gate_holds_one_minute_before():
    one_minute_early = datetime(2026, 8, 19, 18, 29, tzinfo=UTC)
    assert is_live(one_minute_early, SETTINGS, forced=False) is False


def test_gate_opens_one_minute_after():
    one_minute_late = datetime(2026, 8, 19, 18, 31, tzinfo=UTC)
    assert is_live(one_minute_late, SETTINGS, forced=False) is True


def test_gate_opens_exactly_on_the_instant():
    assert is_live(go_live_instant(SETTINGS), SETTINGS, forced=False) is True


def test_force_unlock_overrides_a_closed_gate():
    long_before = datetime(2026, 1, 1, tzinfo=UTC)
    assert is_live(long_before, SETTINGS, forced=True) is True


def test_countdown_is_reported_in_whole_seconds_and_floors_at_zero():
    now = go_live_instant(SETTINGS) - timedelta(seconds=90)
    assert seconds_until_live(now, SETTINGS) == 90
    assert seconds_until_live(go_live_instant(SETTINGS), SETTINGS) == 0
    assert seconds_until_live(datetime(2027, 1, 1, tzinfo=UTC), SETTINGS) == 0
```

- [ ] **Step 7: Run them and confirm they fail**

Run: `cd server && pytest tests/test_golive.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xxvi.auth.golive'`

- [ ] **Step 8: Write `server/xxvi/auth/golive.py`**

```python
from datetime import UTC, datetime

from xxvi.settings import Settings


def go_live_instant(settings: Settings) -> datetime:
    """The configured go-live moment, normalised to UTC.

    Configured as an IST wall-clock time. Stored and compared as a UTC
    instant so the server's own timezone is never load-bearing.
    """
    parsed = datetime.fromisoformat(settings.go_live_iso)
    if parsed.tzinfo is None:
        raise ValueError("go_live_iso must carry an explicit UTC offset")
    return parsed.astimezone(UTC)


def is_live(now: datetime, settings: Settings, *, forced: bool) -> bool:
    if forced:
        return True
    return now >= go_live_instant(settings)


def seconds_until_live(now: datetime, settings: Settings) -> int:
    remaining = (go_live_instant(settings) - now).total_seconds()
    return max(0, int(remaining))
```

- [ ] **Step 9: Run the tests and confirm they pass**

Run: `cd server && pytest tests/test_golive.py -v`
Expected: PASS (6 tests)

- [ ] **Step 10: Commit**

```bash
git add server/xxvi/auth server/tests/test_auth.py server/tests/test_golive.py
git commit -m "feat: add argon2 passwords, signed sessions and the IST timed unlock"
```

---

## Task 7: Gates — hashed codes, attempts, lockout, override

**Files:**
- Create: `server/xxvi/gates/__init__.py`, `server/xxvi/gates/service.py`
- Test: `server/tests/test_gates.py`

**Interfaces:**
- Consumes: `hash_password` / `verify_password` (Task 6); `RunRepository` (Task 5)
- Produces: `GateId` (`ACTIVATION`, `CHECKPOINT_1`, `CHECKPOINT_2`), `GateOutcome` (`OK`, `WRONG`, `LOCKED`), `GATE_POLICY: dict[GateId, GatePolicy]` where `GatePolicy(max_attempts: int | None)` — `None` means never hard-locked. `GateService(repo, settings)` with `async submit(run_id, gate, candidate) -> GateOutcome`, `async clear_lock(run_id, gate) -> None`, `async attempts_remaining(run_id, gate) -> int | None`.

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/test_gates.py
import pytest

from xxvi.auth.passwords import hash_password
from xxvi.gates.service import GateId, GateOutcome, GateService
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings

CORRECT = "ABCD-EFGH-IJKL"


@pytest.fixture
def settings():
    return Settings(
        activation_code_hash=hash_password(CORRECT),
        checkpoint_1_hash=hash_password(CORRECT),
        checkpoint_2_hash=hash_password(CORRECT),
    )


@pytest.fixture
async def service(sessionmaker, settings):
    return GateService(RunRepository(sessionmaker), settings)


@pytest.fixture
async def run(sessionmaker, account):
    from xxvi.core.models import Difficulty

    return await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)


async def test_correct_code_passes(service, run):
    assert await service.submit(run.id, GateId.CHECKPOINT_1, CORRECT) is GateOutcome.OK


async def test_wrong_code_is_rejected(service, run):
    assert await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE") is GateOutcome.WRONG


async def test_checkpoint_locks_after_three_wrong_attempts(service, run):
    for _ in range(3):
        assert await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE") is GateOutcome.WRONG
    assert await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE") is GateOutcome.LOCKED
    # Locked means locked, even for the right answer.
    assert await service.submit(run.id, GateId.CHECKPOINT_1, CORRECT) is GateOutcome.LOCKED


async def test_activation_gate_never_hard_locks(service, run):
    for _ in range(25):
        assert await service.submit(run.id, GateId.ACTIVATION, "NOPE") is GateOutcome.WRONG
    assert await service.submit(run.id, GateId.ACTIVATION, CORRECT) is GateOutcome.OK


async def test_operator_can_clear_a_lockout(service, run):
    for _ in range(3):
        await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE")
    assert await service.submit(run.id, GateId.CHECKPOINT_1, CORRECT) is GateOutcome.LOCKED

    await service.clear_lock(run.id, GateId.CHECKPOINT_1)
    assert await service.submit(run.id, GateId.CHECKPOINT_1, CORRECT) is GateOutcome.OK


async def test_gates_are_tracked_independently(service, run):
    for _ in range(3):
        await service.submit(run.id, GateId.CHECKPOINT_1, "NOPE")
    assert await service.submit(run.id, GateId.CHECKPOINT_2, CORRECT) is GateOutcome.OK


async def test_attempts_remaining_is_none_for_the_unlockable_front_door(service, run):
    assert await service.attempts_remaining(run.id, GateId.ACTIVATION) is None
    assert await service.attempts_remaining(run.id, GateId.CHECKPOINT_1) == 3
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd server && pytest tests/test_gates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xxvi.gates'`

- [ ] **Step 3: Extend `RunRepository` with gate persistence**

Append these methods to `server/xxvi/persistence/repositories.py`:

```python
    async def gate_row(self, run_id: int, gate_id: str) -> GateAttempt:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(GateAttempt).where(
                    GateAttempt.run_id == run_id, GateAttempt.gate_id == gate_id
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = GateAttempt(run_id=run_id, gate_id=gate_id, attempts=0, locked=False)
                session.add(row)
                await session.commit()
            return row

    async def set_gate(self, run_id: int, gate_id: str, *, attempts: int, locked: bool) -> None:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(GateAttempt).where(
                    GateAttempt.run_id == run_id, GateAttempt.gate_id == gate_id
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = GateAttempt(run_id=run_id, gate_id=gate_id)
                session.add(row)
            row.attempts = attempts
            row.locked = locked
            await session.commit()
```

Add `GateAttempt` to the imports at the top of that file.

- [ ] **Step 4: Write `server/xxvi/gates/service.py`**

```python
from dataclasses import dataclass
from enum import StrEnum

from xxvi.auth.passwords import verify_password
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings


class GateId(StrEnum):
    ACTIVATION = "activation"
    CHECKPOINT_1 = "checkpoint_1"
    CHECKPOINT_2 = "checkpoint_2"


class GateOutcome(StrEnum):
    OK = "ok"
    WRONG = "wrong"
    LOCKED = "locked"


@dataclass(frozen=True)
class GatePolicy:
    max_attempts: int | None  # None means rate-limited but never hard-locked


# The front door is never bricked. Checkpoints can afford to be cruel.
GATE_POLICY: dict[GateId, GatePolicy] = {
    GateId.ACTIVATION: GatePolicy(max_attempts=None),
    GateId.CHECKPOINT_1: GatePolicy(max_attempts=3),
    GateId.CHECKPOINT_2: GatePolicy(max_attempts=3),
}


class GateService:
    def __init__(self, repo: RunRepository, settings: Settings) -> None:
        self._repo = repo
        self._settings = settings

    def _expected_hash(self, gate: GateId) -> str:
        return {
            GateId.ACTIVATION: self._settings.activation_code_hash,
            GateId.CHECKPOINT_1: self._settings.checkpoint_1_hash,
            GateId.CHECKPOINT_2: self._settings.checkpoint_2_hash,
        }[gate]

    async def submit(self, run_id: int, gate: GateId, candidate: str) -> GateOutcome:
        row = await self._repo.gate_row(run_id, gate.value)
        policy = GATE_POLICY[gate]

        if row.locked:
            return GateOutcome.LOCKED

        if verify_password(candidate.strip().upper(), self._expected_hash(gate)):
            await self._repo.set_gate(run_id, gate.value, attempts=0, locked=False)
            await self._repo.append_event(run_id, "gate_passed", {"gate": gate.value})
            return GateOutcome.OK

        attempts = row.attempts + 1
        locked = policy.max_attempts is not None and attempts >= policy.max_attempts
        await self._repo.set_gate(run_id, gate.value, attempts=attempts, locked=locked)
        await self._repo.append_event(
            run_id, "gate_failed", {"gate": gate.value, "attempts": attempts}
        )
        return GateOutcome.WRONG

    async def clear_lock(self, run_id: int, gate: GateId) -> None:
        await self._repo.set_gate(run_id, gate.value, attempts=0, locked=False)
        await self._repo.append_event(run_id, "gate_unlocked", {"gate": gate.value})

    async def attempts_remaining(self, run_id: int, gate: GateId) -> int | None:
        policy = GATE_POLICY[gate]
        if policy.max_attempts is None:
            return None
        row = await self._repo.gate_row(run_id, gate.value)
        return max(0, policy.max_attempts - row.attempts)
```

Note: the gate secrets are stored as argon2 hashes generated from the **uppercased, stripped** plaintext, so `submit` normalises the candidate the same way before comparing.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd server && pytest tests/test_gates.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add server/xxvi/gates server/xxvi/persistence/repositories.py server/tests/test_gates.py
git commit -m "feat: add gate service with lockout policy and operator override"
```

---

## Task 8: Vault — one-time, operator-approved code release

The single most security-sensitive file in the project. Isolated so that "never logged, emitted once, operator-approved" is enforced in one auditable place.

**Files:**
- Create: `server/xxvi/vault/__init__.py`, `server/xxvi/vault/service.py`
- Test: `server/tests/test_vault.py`

**Interfaces:**
- Consumes: `Settings` (Task 1); `RunRepository` (Task 5)
- Produces: `AlreadyReleased`, `NotApproved` exceptions; `VaultService(sessionmaker, settings)` with `async release(run_id, reward_id, *, approved_by_operator: bool) -> str` and `async released_reward_ids(run_id) -> frozenset[int]`.

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/test_vault.py
import asyncio
import logging

import pytest

from xxvi.core.models import Difficulty
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings
from xxvi.vault.service import AlreadyReleased, NotApproved, VaultService

SECRET = "REAL-CODE-DO-NOT-LEAK"


@pytest.fixture
def settings():
    return Settings(reward_1_code=SECRET, reward_2_code="SECOND-CODE")


@pytest.fixture
async def run(sessionmaker, account):
    return await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)


@pytest.fixture
def vault(sessionmaker, settings):
    return VaultService(sessionmaker, settings)


async def test_approved_release_returns_the_code(vault, run):
    assert await vault.release(run.id, 1, approved_by_operator=True) == SECRET


async def test_release_without_operator_approval_is_refused(vault, run):
    with pytest.raises(NotApproved):
        await vault.release(run.id, 1, approved_by_operator=False)
    assert await vault.released_reward_ids(run.id) == frozenset()


async def test_a_reward_can_only_be_released_once(vault, run):
    await vault.release(run.id, 1, approved_by_operator=True)
    with pytest.raises(AlreadyReleased):
        await vault.release(run.id, 1, approved_by_operator=True)


async def test_concurrent_releases_yield_exactly_one_winner(vault, run):
    results = await asyncio.gather(
        *(vault.release(run.id, 1, approved_by_operator=True) for _ in range(8)),
        return_exceptions=True,
    )
    successes = [r for r in results if isinstance(r, str)]
    conflicts = [r for r in results if isinstance(r, AlreadyReleased)]
    assert len(successes) == 1
    assert len(conflicts) == 7


async def test_the_code_never_appears_in_log_output(vault, run, caplog):
    with caplog.at_level(logging.DEBUG):
        await vault.release(run.id, 1, approved_by_operator=True)
        with pytest.raises(AlreadyReleased):
            await vault.release(run.id, 1, approved_by_operator=True)
        with pytest.raises(NotApproved):
            await vault.release(run.id, 2, approved_by_operator=False)
    assert SECRET not in caplog.text


async def test_released_ids_are_reported(vault, run):
    await vault.release(run.id, 1, approved_by_operator=True)
    assert await vault.released_reward_ids(run.id) == frozenset({1})
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd server && pytest tests/test_vault.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xxvi.vault'`

- [ ] **Step 3: Write `server/xxvi/vault/service.py`**

```python
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from xxvi.persistence.models import CodeRelease
from xxvi.settings import Settings

logger = logging.getLogger(__name__)


class AlreadyReleased(Exception):
    """This reward has already been emitted for this run."""


class NotApproved(Exception):
    """No operator approval accompanied the request."""


class UnknownReward(Exception):
    """No code is configured for that reward id."""


class VaultService:
    """Custody of the gift card codes.

    Invariants enforced here and nowhere else:
      1. A code is emitted only with explicit operator approval.
      2. A code is emitted at most once per (run, reward) — guaranteed by a
         database UNIQUE constraint, not by application logic.
      3. A code value is never logged, never persisted, and never included
         in an exception message.
    """

    def __init__(self, sessionmaker: async_sessionmaker, settings: Settings) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings

    def _code_for(self, reward_id: int) -> str:
        codes = {1: self._settings.reward_1_code, 2: self._settings.reward_2_code}
        try:
            return codes[reward_id]
        except KeyError:
            raise UnknownReward(f"no code configured for reward {reward_id}") from None

    async def release(self, run_id: int, reward_id: int, *, approved_by_operator: bool) -> str:
        if not approved_by_operator:
            logger.warning("release refused: no operator approval (run=%s reward=%s)", run_id, reward_id)
            raise NotApproved(f"reward {reward_id} requires operator approval")

        code = self._code_for(reward_id)

        # Claim the release first. If the constraint rejects it, nothing is emitted.
        async with self._sessionmaker() as session:
            session.add(CodeRelease(run_id=run_id, reward_id=reward_id))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.info("release rejected as duplicate (run=%s reward=%s)", run_id, reward_id)
                raise AlreadyReleased(f"reward {reward_id} already released") from None

        logger.info("released reward %s for run %s", reward_id, run_id)
        return code

    async def released_reward_ids(self, run_id: int) -> frozenset[int]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(CodeRelease.reward_id).where(CodeRelease.run_id == run_id)
            )
            return frozenset(result.scalars())
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd server && pytest tests/test_vault.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add server/xxvi/vault server/tests/test_vault.py
git commit -m "feat: add vault with one-time operator-approved code release"
```

---

## Task 9: Game seeds, verification, and single-use segment tokens

The server authority protocol from spec §7.

**Files:**
- Create: `server/xxvi/games/__init__.py`, `server/xxvi/games/seeds.py`, `server/xxvi/games/verify.py`, `server/xxvi/games/tokens.py`
- Test: `server/tests/test_games.py`

**Interfaces:**
- Consumes: `Settings` (Task 1); `GameSlot` (Task 2); `RunRepository` (Task 5)
- Produces: `simon_sequence(seed, length) -> list[int]`; `GameResult(mechanic, passed_client_side, duration_ms, input_count, score, sequence)`; `verify_result(slot, seed, result) -> bool`; `SegmentClaim(run_id, segment, seed, nonce)`, `issue_segment_token(run_id, segment, ttl_seconds) -> tuple[str, str]` returning `(token, seed)`, `decode_segment_token(token, max_age) -> SegmentClaim`, `TokenInvalid` exception, `TokenService(repo)` with `async consume(token, run_id) -> SegmentClaim`.

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/test_games.py
import pytest

from xxvi.content.schema import GameSlot
from xxvi.core.models import Difficulty
from xxvi.games.seeds import simon_sequence
from xxvi.games.tokens import TokenInvalid, TokenService, decode_segment_token, issue_segment_token
from xxvi.games.verify import GameResult, verify_result
from xxvi.persistence.repositories import RunRepository


def test_simon_sequence_is_deterministic_for_a_seed():
    assert simon_sequence("seed-a", 6) == simon_sequence("seed-a", 6)


def test_simon_sequence_differs_between_seeds():
    assert simon_sequence("seed-a", 8) != simon_sequence("seed-b", 8)


def test_simon_sequence_is_a_prefix_of_a_longer_one():
    assert simon_sequence("seed-a", 4) == simon_sequence("seed-a", 8)[:4]


def test_simon_values_are_face_buttons():
    assert set(simon_sequence("seed-a", 40)) <= {0, 1, 2, 3}


def test_simon_passes_only_with_the_exact_server_sequence():
    slot = GameSlot(segment=1, mechanic="simon", params={"length": 5})
    correct = simon_sequence("s", 5)

    ok = GameResult(mechanic="simon", passed_client_side=True, duration_ms=6000,
                    input_count=5, score=5, sequence=correct)
    assert verify_result(slot, "s", ok) is True

    wrong = GameResult(mechanic="simon", passed_client_side=True, duration_ms=6000,
                       input_count=5, score=5, sequence=list(reversed(correct)))
    assert verify_result(slot, "s", wrong) is False


def test_simon_ignores_a_lying_client_verdict():
    slot = GameSlot(segment=1, mechanic="simon", params={"length": 5})
    lying = GameResult(mechanic="simon", passed_client_side=True, duration_ms=6000,
                       input_count=5, score=5, sequence=[0, 0, 0, 0, 0])
    assert verify_result(slot, "s", lying) is False


def test_update_game_requires_the_configured_tap_count():
    slot = GameSlot(segment=2, mechanic="update", params={"taps_required": 20})
    enough = GameResult(mechanic="update", passed_client_side=True, duration_ms=9000,
                        input_count=20, score=20, sequence=[])
    short = GameResult(mechanic="update", passed_client_side=True, duration_ms=9000,
                       input_count=11, score=11, sequence=[])
    assert verify_result(slot, "s", enough) is True
    assert verify_result(slot, "s", short) is False


def test_implausibly_fast_runs_are_rejected():
    slot = GameSlot(segment=2, mechanic="update", params={"taps_required": 20})
    too_fast = GameResult(mechanic="update", passed_client_side=True, duration_ms=50,
                          input_count=20, score=20, sequence=[])
    assert verify_result(slot, "s", too_fast) is False


def test_drift_requires_surviving_the_configured_duration():
    slot = GameSlot(segment=3, mechanic="drift", params={"duration_ms": 20000, "drift_rate": 1.0})
    survived = GameResult(mechanic="drift", passed_client_side=True, duration_ms=20000,
                          input_count=140, score=20000, sequence=[])
    quit_early = GameResult(mechanic="drift", passed_client_side=True, duration_ms=9000,
                            input_count=60, score=9000, sequence=[])
    idle = GameResult(mechanic="drift", passed_client_side=True, duration_ms=20000,
                      input_count=0, score=20000, sequence=[])
    assert verify_result(slot, "s", survived) is True
    assert verify_result(slot, "s", quit_early) is False
    assert verify_result(slot, "s", idle) is False, "no inputs means nobody played"


def test_trophy_run_requires_hitting_every_prompt():
    slot = GameSlot(segment=4, mechanic="trophy_run", params={"prompts": 6, "window_ms": 1200})
    cleared = GameResult(mechanic="trophy_run", passed_client_side=True, duration_ms=6000,
                         input_count=6, score=6, sequence=[])
    dropped = GameResult(mechanic="trophy_run", passed_client_side=True, duration_ms=6000,
                         input_count=6, score=5, sequence=[])
    assert verify_result(slot, "s", cleared) is True
    assert verify_result(slot, "s", dropped) is False


def test_token_round_trips_and_carries_a_seed():
    token, seed = issue_segment_token(run_id=1, segment=3, ttl_seconds=600)
    claim = decode_segment_token(token, max_age=600)
    assert claim.run_id == 1
    assert claim.segment == 3
    assert claim.seed == seed


def test_tampered_token_is_rejected():
    token, _ = issue_segment_token(run_id=1, segment=3, ttl_seconds=600)
    with pytest.raises(TokenInvalid):
        decode_segment_token(token[:-1] + "x", max_age=600)


def test_expired_token_is_rejected():
    token, _ = issue_segment_token(run_id=1, segment=3, ttl_seconds=600)
    with pytest.raises(TokenInvalid):
        decode_segment_token(token, max_age=-1)


async def test_a_token_can_only_be_consumed_once(sessionmaker, account):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    service = TokenService(repo)
    token, _ = issue_segment_token(run_id=run.id, segment=1, ttl_seconds=600)

    await service.consume(token, run_id=run.id)
    with pytest.raises(TokenInvalid, match="consumed"):
        await service.consume(token, run_id=run.id)


async def test_a_token_issued_for_another_run_is_rejected(sessionmaker, account):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    service = TokenService(repo)
    token, _ = issue_segment_token(run_id=run.id + 999, segment=1, ttl_seconds=600)

    with pytest.raises(TokenInvalid):
        await service.consume(token, run_id=run.id)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd server && pytest tests/test_games.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xxvi.games'`

- [ ] **Step 3: Write `server/xxvi/games/seeds.py`**

```python
import hashlib

FACE_BUTTONS = 4


def simon_sequence(seed: str, length: int) -> list[int]:
    """Deterministic face-button sequence for a seed.

    Uses a counter-mode hash rather than `random` so that the sequence is
    stable across Python versions, and so a shorter sequence is always a
    prefix of a longer one for the same seed.
    """
    out: list[int] = []
    counter = 0
    while len(out) < length:
        digest = hashlib.sha256(f"{seed}:{counter}".encode()).digest()
        out.extend(byte % FACE_BUTTONS for byte in digest)
        counter += 1
    return out[:length]
```

- [ ] **Step 4: Write `server/xxvi/games/verify.py`**

```python
from dataclasses import dataclass, field

from xxvi.content.schema import GameSlot
from xxvi.games.seeds import simon_sequence

# Nobody presses a key faster than this. Anything quicker did not happen.
MIN_MS_PER_INPUT = 60


@dataclass(frozen=True)
class GameResult:
    mechanic: str
    passed_client_side: bool
    duration_ms: int
    input_count: int
    score: int
    sequence: list[int] = field(default_factory=list)


def verify_result(slot: GameSlot, seed: str, result: GameResult) -> bool:
    """Server-side verdict. `passed_client_side` is advisory and never trusted."""
    if result.mechanic != slot.mechanic:
        return False
    if result.duration_ms < result.input_count * MIN_MS_PER_INPUT:
        return False

    match slot.mechanic:
        case "simon":
            length = int(slot.params.get("length", 4))
            return result.sequence == simon_sequence(seed, length)
        case "update":
            required = int(slot.params.get("taps_required", 20))
            return result.input_count >= required
        case "drift":
            duration = int(slot.params.get("duration_ms", 20000))
            return result.duration_ms >= duration and result.input_count > 0
        case "trophy_run":
            prompts = int(slot.params.get("prompts", 6))
            return result.score >= prompts and result.input_count >= prompts
        case _:
            return False
```

- [ ] **Step 5: Write `server/xxvi/games/tokens.py`**

```python
import secrets
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from xxvi.persistence.repositories import RunRepository
from xxvi.settings import get_settings

_SALT = "xxvi.segment.v1"
CONSUMED_EVENT = "segment_token_consumed"


class TokenInvalid(Exception):
    """Bad signature, expired, wrong run, or already consumed."""


@dataclass(frozen=True)
class SegmentClaim:
    run_id: int
    segment: int
    seed: str
    nonce: str


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt=_SALT)


def issue_segment_token(run_id: int, segment: int, ttl_seconds: int = 600) -> tuple[str, str]:
    """Returns (token, seed). The seed is sent to the client; the server keeps
    the authoritative copy inside the signed token."""
    seed = secrets.token_urlsafe(12)
    nonce = secrets.token_urlsafe(9)
    token = _serializer().dumps(
        {"run_id": run_id, "segment": segment, "seed": seed, "nonce": nonce}
    )
    return token, seed


def decode_segment_token(token: str, max_age: int = 600) -> SegmentClaim:
    try:
        payload = _serializer().loads(token, max_age=max_age)
    except SignatureExpired:
        raise TokenInvalid("segment token expired") from None
    except BadSignature:
        raise TokenInvalid("segment token signature invalid") from None
    return SegmentClaim(
        run_id=int(payload["run_id"]),
        segment=int(payload["segment"]),
        seed=str(payload["seed"]),
        nonce=str(payload["nonce"]),
    )


class TokenService:
    """Enforces single use. Consumed nonces live in the run event log rather
    than a dedicated table — the audit trail is wanted regardless."""

    def __init__(self, repo: RunRepository) -> None:
        self._repo = repo

    async def consume(self, token: str, run_id: int, max_age: int = 600) -> SegmentClaim:
        claim = decode_segment_token(token, max_age=max_age)
        if claim.run_id != run_id:
            raise TokenInvalid("segment token belongs to another run")
        if await self._repo.has_event(run_id, CONSUMED_EVENT, {"nonce": claim.nonce}):
            raise TokenInvalid("segment token already consumed")
        await self._repo.append_event(
            run_id, CONSUMED_EVENT, {"nonce": claim.nonce, "segment": claim.segment}
        )
        return claim
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `cd server && pytest tests/test_games.py -v`
Expected: PASS (15 tests)

- [ ] **Step 7: Commit**

```bash
git add server/xxvi/games server/tests/test_games.py
git commit -m "feat: add seeded game verification and single-use segment tokens"
```

---

## Task 10: Realtime — message contracts and the hub

WebSocket messages do not go through OpenAPI, so this is the one seam where drift is possible. Every message type lives in exactly one file on each side.

**Files:**
- Create: `server/xxvi/realtime/__init__.py`, `server/xxvi/realtime/messages.py`, `server/xxvi/realtime/hub.py`
- Test: `server/tests/test_realtime.py`

**Interfaces:**
- Consumes: nothing
- Produces: Pydantic models `RunStateMsg`, `TrophyPopMsg`, `CodeReleasedMsg`, `ToastMsg`, `OperatorPresenceMsg`, `GateResultMsg`, and the union `ServerMessage`. `Hub` with `async connect(channel, websocket)`, `async disconnect(channel, websocket)`, `async broadcast(channel, message: ServerMessage) -> int` (returns delivery count), `def operator_online() -> bool`. Channels are `"player:{run_id}"` and `"operator"`.

- [ ] **Step 1: Write `server/xxvi/realtime/messages.py`**

```python
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class RunStateMsg(BaseModel):
    type: Literal["run_state"] = "run_state"
    phase: str
    segment: int
    difficulty: str | None
    cleared_segments: list[int]
    released_rewards: list[int]


class TrophyPopMsg(BaseModel):
    type: Literal["trophy_pop"] = "trophy_pop"
    trophy_id: str
    name: str
    grade: str


class CodeReleasedMsg(BaseModel):
    type: Literal["code_released"] = "code_released"
    reward_id: int
    label: str
    code: str  # only ever sent on the player channel, after operator approval


class ToastMsg(BaseModel):
    type: Literal["toast"] = "toast"
    text: str


class OperatorPresenceMsg(BaseModel):
    type: Literal["operator_presence"] = "operator_presence"
    online: bool


class GateResultMsg(BaseModel):
    type: Literal["gate_result"] = "gate_result"
    gate: str
    outcome: str
    attempts_remaining: int | None


ServerMessage = Annotated[
    RunStateMsg
    | TrophyPopMsg
    | CodeReleasedMsg
    | ToastMsg
    | OperatorPresenceMsg
    | GateResultMsg,
    Field(discriminator="type"),
]
```

- [ ] **Step 2: Write the failing tests**

```python
# server/tests/test_realtime.py
from xxvi.realtime.hub import Hub
from xxvi.realtime.messages import ToastMsg, TrophyPopMsg


class FakeSocket:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self.fail = fail

    async def send_json(self, payload: dict) -> None:
        if self.fail:
            raise RuntimeError("socket is gone")
        self.sent.append(payload)


async def test_broadcast_reaches_every_socket_on_a_channel():
    hub = Hub()
    a, b = FakeSocket(), FakeSocket()
    await hub.connect("player:1", a)
    await hub.connect("player:1", b)

    delivered = await hub.broadcast("player:1", ToastMsg(text="bro"))

    assert delivered == 2
    assert a.sent[0]["type"] == "toast"
    assert b.sent[0]["text"] == "bro"


async def test_channels_are_isolated():
    hub = Hub()
    player, operator = FakeSocket(), FakeSocket()
    await hub.connect("player:1", player)
    await hub.connect("operator", operator)

    await hub.broadcast("player:1", ToastMsg(text="only for him"))

    assert len(player.sent) == 1
    assert operator.sent == []


async def test_a_dead_socket_is_dropped_without_breaking_the_broadcast():
    hub = Hub()
    dead, alive = FakeSocket(fail=True), FakeSocket()
    await hub.connect("player:1", dead)
    await hub.connect("player:1", alive)

    delivered = await hub.broadcast("player:1", TrophyPopMsg(trophy_id="game-1", name="n", grade="bronze"))

    assert delivered == 1
    assert len(alive.sent) == 1
    assert await hub.broadcast("player:1", ToastMsg(text="again")) == 1


async def test_operator_presence_tracks_connections():
    hub = Hub()
    assert hub.operator_online() is False
    socket = FakeSocket()
    await hub.connect("operator", socket)
    assert hub.operator_online() is True
    await hub.disconnect("operator", socket)
    assert hub.operator_online() is False


async def test_broadcast_to_an_empty_channel_is_harmless():
    assert await Hub().broadcast("player:99", ToastMsg(text="nobody home")) == 0
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `cd server && pytest tests/test_realtime.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xxvi.realtime.hub'`

- [ ] **Step 4: Write `server/xxvi/realtime/hub.py`**

```python
import logging
from collections import defaultdict
from typing import Any, Protocol

from xxvi.realtime.messages import ServerMessage

logger = logging.getLogger(__name__)

OPERATOR_CHANNEL = "operator"


def player_channel(run_id: int) -> str:
    return f"player:{run_id}"


class SocketLike(Protocol):
    async def send_json(self, payload: dict[str, Any]) -> None: ...


class Hub:
    """In-process fan-out. Single instance by design — one player, one operator."""

    def __init__(self) -> None:
        self._channels: dict[str, set[SocketLike]] = defaultdict(set)

    async def connect(self, channel: str, socket: SocketLike) -> None:
        self._channels[channel].add(socket)

    async def disconnect(self, channel: str, socket: SocketLike) -> None:
        self._channels[channel].discard(socket)

    def operator_online(self) -> bool:
        return bool(self._channels.get(OPERATOR_CHANNEL))

    async def broadcast(self, channel: str, message: ServerMessage) -> int:
        payload = message.model_dump()
        delivered = 0
        for socket in list(self._channels.get(channel, ())):
            try:
                await socket.send_json(payload)
                delivered += 1
            except Exception:
                # A dead socket must never break a trophy pop for anyone else.
                logger.info("dropping dead socket on channel %s", channel)
                self._channels[channel].discard(socket)
        return delivered


hub = Hub()
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd server && pytest tests/test_realtime.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add server/xxvi/realtime server/tests/test_realtime.py
git commit -m "feat: add websocket message contracts and fan-out hub"
```

---

## Task 11: API — auth routes and the coming-soon gate

**Files:**
- Create: `server/xxvi/api/__init__.py`, `server/xxvi/api/deps.py`, `server/xxvi/api/auth_routes.py`
- Modify: `server/xxvi/main.py` (mount routers, seed accounts on startup)
- Test: `server/tests/test_api_auth.py`

**Interfaces:**
- Consumes: `SessionData`, `issue_session`, `read_session`, `verify_password` (Task 6); `is_live`, `seconds_until_live` (Task 6); `Account` (Task 5)
- Produces: `POST /api/auth/login {username, password} -> {role}` setting the session cookie; `POST /api/auth/logout`; `GET /api/session -> SessionInfo{authenticated, role, live, seconds_until_live}`. Dependencies `current_session(request) -> SessionData | None`, `require_player(...) -> SessionData`, `require_operator(...) -> SessionData`, `require_live(...) -> None`. `seed_accounts(sessionmaker, settings) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/test_api_auth.py
import pytest
from httpx import ASGITransport, AsyncClient

from xxvi.auth.passwords import hash_password
from xxvi.main import create_app
from xxvi.settings import Settings, get_settings


@pytest.fixture
def settings():
    return Settings(
        player_username="him",
        player_password_hash=hash_password("pw-him"),
        operator_username="me",
        operator_password_hash=hash_password("pw-me"),
        go_live_iso="2026-08-20T00:00:00+05:30",
    )


@pytest.fixture
async def client(sessionmaker, settings):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.sessionmaker = sessionmaker
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
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
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd server && pytest tests/test_api_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xxvi.api'`

- [ ] **Step 3: Write `server/xxvi/api/deps.py`**

```python
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import async_sessionmaker

from xxvi.auth.golive import is_live
from xxvi.auth.sessions import SESSION_COOKIE, SessionData, read_session
from xxvi.settings import Settings, get_settings


def get_sessionmaker_dep(request: Request) -> async_sessionmaker:
    return request.app.state.sessionmaker


def force_unlocked(request: Request) -> bool:
    return bool(getattr(request.app.state, "force_unlocked", False))


def current_session(request: Request) -> SessionData | None:
    token = request.cookies.get(SESSION_COOKIE)
    return read_session(token) if token else None


def require_session(session: SessionData | None = Depends(current_session)) -> SessionData:
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    return session


def require_player(session: SessionData = Depends(require_session)) -> SessionData:
    if session.role != "player":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "player role required")
    return session


def require_operator(session: SessionData = Depends(require_session)) -> SessionData:
    if session.role != "operator":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "operator role required")
    return session


def require_live(
    settings: Settings = Depends(get_settings),
    forced: bool = Depends(force_unlocked),
) -> None:
    if not is_live(datetime.now(UTC), settings, forced=forced):
        raise HTTPException(status.HTTP_423_LOCKED, "not yet")
```

- [ ] **Step 4: Write `server/xxvi/api/auth_routes.py`**

```python
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from xxvi.api.deps import current_session, force_unlocked, get_sessionmaker_dep
from xxvi.auth.golive import is_live, seconds_until_live
from xxvi.auth.passwords import verify_password
from xxvi.auth.sessions import SESSION_COOKIE, SessionData, issue_session
from xxvi.persistence.models import Account
from xxvi.settings import Settings, get_settings

router = APIRouter(prefix="/api")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    role: str


class SessionInfo(BaseModel):
    authenticated: bool
    role: str | None
    live: bool
    seconds_until_live: int


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    response: Response,
    sessionmaker: async_sessionmaker = Depends(get_sessionmaker_dep),
) -> LoginResponse:
    async with sessionmaker() as session:
        result = await session.execute(select(Account).where(Account.username == body.username))
        account = result.scalar_one_or_none()

    if account is None or not verify_password(body.password, account.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    token = issue_session(SessionData(account_id=account.id, role=account.role))
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=True)
    return LoginResponse(role=account.role)


@router.post("/auth/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/session", response_model=SessionInfo)
async def session_info(
    session: SessionData | None = Depends(current_session),
    settings: Settings = Depends(get_settings),
    forced: bool = Depends(force_unlocked),
) -> SessionInfo:
    now = datetime.now(UTC)
    return SessionInfo(
        authenticated=session is not None,
        role=session.role if session else None,
        live=is_live(now, settings, forced=forced),
        seconds_until_live=seconds_until_live(now, settings),
    )
```

- [ ] **Step 5: Update `server/xxvi/main.py`**

```python
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from xxvi.api import auth_routes
from xxvi.persistence.models import Account
from xxvi.persistence.session import get_sessionmaker
from xxvi.settings import Settings, get_settings

health_router = APIRouter()


@health_router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def seed_accounts(sessionmaker: async_sessionmaker, settings: Settings) -> None:
    """Two accounts, from env. No signup, no recovery. Idempotent."""
    wanted = [
        (settings.player_username, settings.player_password_hash, "player"),
        (settings.operator_username, settings.operator_password_hash, "operator"),
    ]
    async with sessionmaker() as session:
        for username, password_hash, role in wanted:
            if not username or not password_hash:
                continue
            result = await session.execute(select(Account).where(Account.username == username))
            account = result.scalar_one_or_none()
            if account is None:
                session.add(Account(username=username, password_hash=password_hash, role=role))
            else:
                account.password_hash = password_hash
                account.role = role
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "sessionmaker"):
        app.state.sessionmaker = get_sessionmaker()
    app.state.force_unlocked = False
    await seed_accounts(app.state.sessionmaker, get_settings())
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="XXVI",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.force_unlocked = False
    app.include_router(health_router)
    app.include_router(auth_routes.router)
    return app


app = create_app()
```

- [ ] **Step 6: Seed the test accounts in the fixture**

Add to `server/tests/test_api_auth.py`'s `client` fixture, before yielding:

```python
    from xxvi.main import seed_accounts
    await seed_accounts(sessionmaker, settings)
```

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `cd server && pytest tests/test_api_auth.py -v`
Expected: PASS (7 tests)

- [ ] **Step 8: Commit**

```bash
git add server/xxvi/api server/xxvi/main.py server/tests/test_api_auth.py
git commit -m "feat: add login, session info and role dependencies"
```

---

## Task 11b: Public content endpoint and dry-run mode

The frontend needs the trophy catalogue and the copy block, and hidden trophy names must be masked **server-side** — masking them only in the client would put them in the bundle for anyone who opens devtools. Dry-run mode is spec §2.0's rehearsal path.

**Files:**
- Create: `server/xxvi/api/content_routes.py`
- Modify: `server/xxvi/api/deps.py` (dry-run bypass), `server/xxvi/vault/service.py` (dummy codes), `server/xxvi/main.py` (mount)
- Test: `server/tests/test_api_content.py`, `server/tests/test_dry_run.py`

**Interfaces:**
- Consumes: `RunConfig` (Task 2); `require_live` (Task 11); `VaultService` (Task 8)
- Produces: `GET /api/content -> ContentView{copy: CopyView, trophies: list[TrophyView]}` where `TrophyView{id, name, grade, hidden}` and a hidden trophy's `name` is `"???"` until earned. `VaultService.release(..., dry_run=...)` returns `DRY-RUN-{reward_id}` without touching the real code.

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/test_api_content.py
import pytest
from httpx import ASGITransport, AsyncClient

from xxvi.content.loader import load_config
from xxvi.main import create_app
from xxvi.settings import Settings, get_settings
from tests.paths import EXAMPLE_CONFIG


@pytest.fixture
async def client(sessionmaker):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings()
    app.state.sessionmaker = sessionmaker
    app.state.config = load_config(EXAMPLE_CONFIG)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_content_is_readable_without_signing_in(client):
    assert (await client.get("/api/content")).status_code == 200


async def test_hidden_trophy_names_are_masked_server_side(client):
    body = (await client.get("/api/content")).json()
    hidden = [t for t in body["trophies"] if t["hidden"]]
    assert hidden, "the example config defines hidden trophies"
    assert all(t["name"] == "???" for t in hidden)


async def test_standard_trophy_names_are_present(client):
    body = (await client.get("/api/content")).json()
    platinum = next(t for t in body["trophies"] if t["id"] == "platinum")
    assert platinum["name"] != "???"


async def test_question_text_is_not_served_by_the_content_endpoint(client):
    raw = (await client.get("/api/content")).text
    assert "placeholder" not in raw.lower() or "roast" not in raw.lower()
    body = (await client.get("/api/content")).json()
    assert "questions" not in body
```

```python
# server/tests/test_dry_run.py
import pytest
from httpx import ASGITransport, AsyncClient

from xxvi.auth.passwords import hash_password
from xxvi.core.models import Difficulty
from xxvi.main import create_app, seed_accounts
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings
from xxvi.vault.service import VaultService

REAL = "REAL-CODE-NEVER-IN-A-REHEARSAL"


async def test_dry_run_release_never_returns_the_real_code(sessionmaker, account):
    run = await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)
    vault = VaultService(sessionmaker, Settings(reward_1_code=REAL, dry_run=True))
    code = await vault.release(run.id, 1, approved_by_operator=True)
    assert code != REAL
    assert code.startswith("DRY-RUN")


async def test_dry_run_lets_the_operator_in_before_go_live(sessionmaker):
    settings = Settings(
        operator_username="me", operator_password_hash=hash_password("pw"),
        player_username="him", player_password_hash=hash_password("pw"),
        go_live_iso="2030-01-01T00:00:00+05:30", dry_run=True,
    )
    app = create_app()
    app.dependency_overrides[__import__("xxvi.settings", fromlist=["get_settings"]).get_settings] = lambda: settings
    app.state.sessionmaker = sessionmaker
    await seed_accounts(sessionmaker, settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/auth/login", json={"username": "me", "password": "pw"})
        assert (await c.get("/api/run")).status_code != 423

        await c.post("/api/auth/logout")
        await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
        # Dry run is for the operator only. He still waits for midnight.
        assert (await c.get("/api/run")).status_code == 423
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd server && pytest tests/test_api_content.py tests/test_dry_run.py -v`
Expected: FAIL — 404 on `/api/content`, and `dry_run` is unused

- [ ] **Step 3: Write `server/xxvi/api/content_routes.py`**

```python
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from xxvi.api.deps import current_session
from xxvi.auth.sessions import SessionData
from xxvi.content.loader import get_config
from xxvi.persistence.repositories import RunRepository

router = APIRouter(prefix="/api")

MASK = "???"


class TrophyView(BaseModel):
    id: str
    name: str
    grade: str
    hidden: bool


class CopyView(BaseModel):
    coming_soon: str
    teaser: str
    how_to_play: str
    closing: str


class ContentView(BaseModel):
    copy: CopyView
    trophies: list[TrophyView]


@router.get("/content", response_model=ContentView)
async def content(
    request: Request,
    session: SessionData | None = Depends(current_session),
) -> ContentView:
    config = getattr(request.app.state, "config", None) or get_config()

    earned: frozenset[str] = frozenset()
    if session is not None:
        repo = RunRepository(request.app.state.sessionmaker)
        run = await repo.get_by_account(session.account_id)
        if run is not None:
            earned = await repo.earned_trophies(run.id)

    return ContentView(
        copy=CopyView(**config.copy.model_dump()),
        trophies=[
            TrophyView(
                id=t.id,
                # Masked here, not in the client — otherwise the names ship
                # in the bundle and devtools spoils them.
                name=MASK if (t.hidden and t.id not in earned) else t.name,
                grade=t.grade,
                hidden=t.hidden,
            )
            for t in config.trophies
        ],
    )
```

Questions are deliberately absent from this payload — they arrive one at a time from `/api/run`, without the answer key.

- [ ] **Step 4: Add the dry-run bypass to `server/xxvi/api/deps.py`**

```python
def require_live(
    settings: Settings = Depends(get_settings),
    forced: bool = Depends(force_unlocked),
    session: SessionData | None = Depends(current_session),
) -> None:
    # Dry run is a rehearsal path for the operator only. He still waits.
    if settings.dry_run and session is not None and session.role == "operator":
        return
    if not is_live(datetime.now(UTC), settings, forced=forced):
        raise HTTPException(status.HTTP_423_LOCKED, "not yet")
```

- [ ] **Step 5: Add dry-run handling to `VaultService._code_for`**

```python
    def _code_for(self, reward_id: int) -> str:
        if reward_id not in (1, 2):
            raise UnknownReward(f"no code configured for reward {reward_id}")
        if self._settings.dry_run:
            # A rehearsal must never emit — or even read — the real value.
            return f"DRY-RUN-REWARD-{reward_id}"
        return {1: self._settings.reward_1_code, 2: self._settings.reward_2_code}[reward_id]
```

- [ ] **Step 6: Mount the router in `create_app()`**

```python
from xxvi.api import auth_routes, content_routes, run_routes
...
    app.include_router(content_routes.router)
```

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `cd server && pytest tests/test_api_content.py tests/test_dry_run.py -v`
Expected: PASS (6 tests)

- [ ] **Step 8: Commit**

```bash
git add server/xxvi/api server/xxvi/vault server/tests/test_api_content.py server/tests/test_dry_run.py
git commit -m "feat: add content endpoint with server-side hidden masking and dry-run mode"
```

---

## Task 12: Run service and player routes

The whole player flow. This is the last task on the never-cross line for the backend.

**Files:**
- Create: `server/xxvi/api/run_service.py`, `server/xxvi/api/run_routes.py`
- Modify: `server/xxvi/main.py` (mount the router)
- Test: `server/tests/test_api_run.py`

**Interfaces:**
- Consumes: everything from Tasks 2–10
- Produces: `RunService` with `async load(account_id) -> tuple[Run, RunState]`, `async apply(run, state, event, **kw) -> ApplyOutcome`, `async start_segment(run, state) -> SegmentBrief`, `async submit_game(run, state, token, result) -> ApplyOutcome`, `async submit_answer(run, state, choice) -> ApplyOutcome`, `async submit_gate(run, state, gate, candidate) -> GateSubmitOutcome`. `ApplyOutcome(state, trophies: list[Trophy], released: CodeReleasedMsg | None)`. Routes: `GET /api/run`, `POST /api/run/activate`, `POST /api/run/profile`, `POST /api/run/difficulty`, `POST /api/run/installed`, `POST /api/run/howto`, `POST /api/run/segment/start`, `POST /api/run/segment/game`, `POST /api/run/segment/answer`, `POST /api/run/checkpoint`.

- [ ] **Step 1: Write the failing end-to-end tests**

These are spec §10's two required end-to-end paths.

```python
# server/tests/test_api_run.py
import pytest
from httpx import ASGITransport, AsyncClient

from xxvi.auth.passwords import hash_password
from xxvi.content.loader import load_config
from xxvi.games.seeds import simon_sequence
from xxvi.main import create_app, seed_accounts
from xxvi.settings import Settings, get_settings
from tests.paths import EXAMPLE_CONFIG

CODE = "ABCD-EFGH-IJKL"


@pytest.fixture
def settings():
    return Settings(
        player_username="him", player_password_hash=hash_password("pw"),
        operator_username="me", operator_password_hash=hash_password("pw"),
        activation_code_hash=hash_password(CODE),
        checkpoint_1_hash=hash_password(CODE),
        checkpoint_2_hash=hash_password(CODE),
        reward_1_code="R1", reward_2_code="R2",
        go_live_iso="2020-01-01T00:00:00+05:30",  # already live
    )


@pytest.fixture
async def client(sessionmaker, settings):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.sessionmaker = sessionmaker
    app.state.config = load_config(EXAMPLE_CONFIG)
    app.state.auto_approve_releases = True  # operator stand-in for tests
    await seed_accounts(sessionmaker, settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
        yield c


async def reach_first_game(client, difficulty: str) -> None:
    await client.post("/api/run/activate", json={"code": CODE})
    await client.post("/api/run/profile")
    await client.post("/api/run/difficulty", json={"difficulty": difficulty})
    await client.post("/api/run/installed")
    await client.post("/api/run/howto")


async def clear_segment(client, config) -> dict:
    brief = (await client.post("/api/run/segment/start")).json()
    slot = next(g for g in config.games if g.segment == brief["segment"])
    result = {
        "mechanic": slot.mechanic,
        "passed_client_side": True,
        "duration_ms": 60000,
        "input_count": 200,
        "score": 999,
        "sequence": simon_sequence(brief["seed"], int(slot.params.get("length", 4)))
        if slot.mechanic == "simon" else [],
    }
    await client.post(
        "/api/run/segment/game", json={"token": brief["token"], "result": result}
    )
    question = (await client.get("/api/run")).json()["question"]
    answer = config.questions[brief["segment"] - 1].answer
    return (await client.post("/api/run/segment/answer", json={"choice": answer})).json()


async def test_question_choices_are_sent_but_the_answer_is_not(client):
    await reach_first_game(client, "kiddie")
    await client.post("/api/run/segment/start")
    body = (await client.get("/api/run")).json()
    assert "choices" in body["question"]
    assert "answer" not in body["question"]


async def test_clean_run_releases_both_rewards(client):
    config = load_config(EXAMPLE_CONFIG)
    await reach_first_game(client, "kiddie")

    for _ in range(4):
        await clear_segment(client, config)
    first = (await client.post("/api/run/checkpoint", json={"code": CODE})).json()
    assert first["released"]["code"] == "R1"

    for _ in range(4):
        await clear_segment(client, config)
    second = (await client.post("/api/run/checkpoint", json={"code": CODE})).json()
    assert second["released"]["code"] == "R2"

    final = (await client.get("/api/run")).json()
    assert final["phase"] == "complete"
    assert "platinum" in final["trophies"]


async def test_devil_wipe_in_act_two_keeps_reward_one(client):
    config = load_config(EXAMPLE_CONFIG)
    await reach_first_game(client, "devil")

    for _ in range(4):
        await clear_segment(client, config)
    await client.post("/api/run/checkpoint", json={"code": CODE})
    await clear_segment(client, config)  # segment 5

    # Fail segment 6 on purpose.
    brief = (await client.post("/api/run/segment/start")).json()
    await client.post("/api/run/segment/game", json={
        "token": brief["token"],
        "result": {"mechanic": "update", "passed_client_side": True,
                   "duration_ms": 100, "input_count": 1, "score": 0, "sequence": []},
    })

    body = (await client.get("/api/run")).json()
    assert body["segment"] == 1
    assert body["cleared_segments"] == []
    assert body["released_rewards"] == [1], "earned codes are never revoked"
    assert body["trophies"] == []


async def test_a_wrong_answer_restarts_the_whole_segment_in_kiddie(client):
    config = load_config(EXAMPLE_CONFIG)
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    slot = config.games[0]
    await client.post("/api/run/segment/game", json={
        "token": brief["token"],
        "result": {"mechanic": slot.mechanic, "passed_client_side": True,
                   "duration_ms": 60000, "input_count": 200, "score": 999,
                   "sequence": simon_sequence(brief["seed"], int(slot.params["length"]))},
    })
    wrong = (config.questions[0].answer + 1) % len(config.questions[0].choices)
    await client.post("/api/run/segment/answer", json={"choice": wrong})

    body = (await client.get("/api/run")).json()
    assert body["phase"] == "game", "restart means the game again, not the question"
    assert body["segment"] == 1


async def test_a_segment_token_cannot_be_replayed(client):
    config = load_config(EXAMPLE_CONFIG)
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    slot = config.games[0]
    payload = {"token": brief["token"],
               "result": {"mechanic": slot.mechanic, "passed_client_side": True,
                          "duration_ms": 60000, "input_count": 200, "score": 999,
                          "sequence": simon_sequence(brief["seed"], int(slot.params["length"]))}}
    assert (await client.post("/api/run/segment/game", json=payload)).status_code == 200
    assert (await client.post("/api/run/segment/game", json=payload)).status_code == 409


async def test_the_run_endpoint_requires_a_signed_in_player(sessionmaker, settings):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.sessionmaker = sessionmaker
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        assert (await anon.get("/api/run")).status_code == 401
```

Create `server/tests/paths.py`:

```python
from pathlib import Path

EXAMPLE_CONFIG = Path(__file__).parents[2] / "config" / "run.example.yaml"
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd server && pytest tests/test_api_run.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xxvi.api.run_service'`

- [ ] **Step 3: Write `server/xxvi/api/run_service.py`**

```python
from dataclasses import dataclass, field

from xxvi.content.schema import RunConfig, Trophy
from xxvi.core.machine import advance
from xxvi.core.models import Difficulty, Event, Phase, RunState, Shape
from xxvi.core.trophies import PLATINUM_ID, platinum_earned, trophy_for
from xxvi.gates.service import GateId, GateOutcome, GateService
from xxvi.games.tokens import TokenService, issue_segment_token
from xxvi.games.verify import GameResult, verify_result
from xxvi.persistence.models import Run
from xxvi.persistence.repositories import RunRepository
from xxvi.realtime.messages import CodeReleasedMsg
from xxvi.vault.service import AlreadyReleased, VaultService


@dataclass(frozen=True)
class SegmentBrief:
    segment: int
    token: str
    seed: str
    mechanic: str
    params: dict


@dataclass
class ApplyOutcome:
    state: RunState
    trophies: list[Trophy] = field(default_factory=list)
    released: CodeReleasedMsg | None = None


class RunService:
    def __init__(
        self,
        repo: RunRepository,
        config: RunConfig,
        gates: GateService,
        vault: VaultService,
        tokens: TokenService,
    ) -> None:
        self._repo = repo
        self._config = config
        self._gates = gates
        self._vault = vault
        self._tokens = tokens
        self._shape = Shape(acts=config.acts, segments_per_act=config.segments_per_act)

    @property
    def shape(self) -> Shape:
        return self._shape

    def _trophy(self, trophy_id: str) -> Trophy:
        return next(t for t in self._config.trophies if t.id == trophy_id)

    async def load(self, account_id: int) -> tuple[Run, RunState]:
        run = await self._repo.get_by_account(account_id)
        if run is None:
            run = await self._repo.create(account_id, None)
        state = RunState(
            phase=Phase(run.phase),
            difficulty=Difficulty(run.difficulty) if run.difficulty else None,
            segment=run.segment,
            cleared_segments=frozenset(run.cleared_segments or []),
            released_rewards=frozenset(run.released_rewards or []),
        )
        return run, state

    async def apply(
        self, run: Run, state: RunState, event: Event, *, difficulty: Difficulty | None = None
    ) -> ApplyOutcome:
        new_state = advance(state, event, self._shape, difficulty=difficulty)
        await self._repo.append_event(run.id, event.value, {"segment": state.segment})

        outcome = ApplyOutcome(state=new_state)

        if event in (Event.GAME_FAILED, Event.QUESTION_FAILED) and state.difficulty is Difficulty.DEVIL:
            await self._repo.clear_segment_trophies(run.id)

        awarded = trophy_for(state, event, self._shape)
        if awarded and await self._repo.award_trophy(run.id, awarded):
            outcome.trophies.append(self._trophy(awarded))

        earned = await self._repo.earned_trophies(run.id)
        if platinum_earned(earned, self._shape) and await self._repo.award_trophy(run.id, PLATINUM_ID):
            outcome.trophies.append(self._trophy(PLATINUM_ID))

        await self._repo.save_state(run.id, new_state)
        return outcome

    async def start_segment(self, run: Run, state: RunState) -> SegmentBrief:
        slot = next(g for g in self._config.games if g.segment == state.segment)
        token, seed = issue_segment_token(run.id, state.segment)
        return SegmentBrief(
            segment=state.segment, token=token, seed=seed,
            mechanic=slot.mechanic, params=dict(slot.params),
        )

    async def submit_game(
        self, run: Run, state: RunState, token: str, result: GameResult
    ) -> ApplyOutcome:
        claim = await self._tokens.consume(token, run_id=run.id)
        slot = next(g for g in self._config.games if g.segment == claim.segment)
        passed = claim.segment == state.segment and verify_result(slot, claim.seed, result)
        return await self.apply(run, state, Event.GAME_PASSED if passed else Event.GAME_FAILED)

    async def submit_answer(self, run: Run, state: RunState, choice: int) -> ApplyOutcome:
        question = self._config.questions[state.segment - 1]
        passed = choice == question.answer
        return await self.apply(
            run, state, Event.QUESTION_PASSED if passed else Event.QUESTION_FAILED
        )

    async def submit_checkpoint(
        self, run: Run, state: RunState, candidate: str, *, approved: bool
    ) -> tuple[GateOutcome, ApplyOutcome | None]:
        act = (state.segment - 1) // self._shape.segments_per_act + 1
        gate = GateId.CHECKPOINT_1 if act == 1 else GateId.CHECKPOINT_2
        verdict = await self._gates.submit(run.id, gate, candidate)
        if verdict is not GateOutcome.OK:
            return verdict, None

        outcome = await self.apply(run, state, Event.CHECKPOINT_PASSED)
        reward = next(r for r in self._config.rewards if r.after_act == act)
        try:
            code = await self._vault.release(run.id, reward.id, approved_by_operator=approved)
            outcome.released = CodeReleasedMsg(reward_id=reward.id, label=reward.label, code=code)
        except AlreadyReleased:
            outcome.released = None
        return verdict, outcome
```

- [ ] **Step 4: Write `server/xxvi/api/run_routes.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from xxvi.api.deps import require_live, require_player
from xxvi.auth.sessions import SessionData
from xxvi.content.loader import get_config
from xxvi.core.models import Difficulty, Event, Phase
from xxvi.gates.service import GateId, GateOutcome, GateService
from xxvi.games.tokens import TokenInvalid, TokenService
from xxvi.games.verify import GameResult
from xxvi.persistence.repositories import RunRepository
from xxvi.realtime.hub import hub, player_channel
from xxvi.realtime.messages import CodeReleasedMsg, RunStateMsg, TrophyPopMsg
from xxvi.settings import Settings, get_settings
from xxvi.vault.service import VaultService

router = APIRouter(prefix="/api/run", dependencies=[Depends(require_live)])


class QuestionView(BaseModel):
    prompt: str
    choices: list[str]  # the answer index is deliberately absent


class RunView(BaseModel):
    phase: str
    segment: int
    difficulty: str | None
    cleared_segments: list[int]
    released_rewards: list[int]
    trophies: list[str]
    question: QuestionView | None


class ActivateRequest(BaseModel):
    code: str


class DifficultyRequest(BaseModel):
    difficulty: Difficulty


class GameSubmission(BaseModel):
    token: str
    result: GameResultBody


class GameResultBody(BaseModel):
    mechanic: str
    passed_client_side: bool
    duration_ms: int
    input_count: int
    score: int
    sequence: list[int] = []


class AnswerRequest(BaseModel):
    choice: int


class CheckpointRequest(BaseModel):
    code: str


def build_service(request: Request, settings: Settings) -> "RunService":
    from xxvi.api.run_service import RunService

    sessionmaker = request.app.state.sessionmaker
    config = getattr(request.app.state, "config", None) or get_config()
    repo = RunRepository(sessionmaker)
    return RunService(
        repo=repo,
        config=config,
        gates=GateService(repo, settings),
        vault=VaultService(sessionmaker, settings),
        tokens=TokenService(repo),
    )


async def _view(service, run, state) -> RunView:
    trophies = await service._repo.earned_trophies(run.id)
    question = None
    if state.phase is Phase.QUESTION:
        q = service._config.questions[state.segment - 1]
        question = QuestionView(prompt=q.prompt, choices=q.choices)
    return RunView(
        phase=state.phase.value,
        segment=state.segment,
        difficulty=state.difficulty.value if state.difficulty else None,
        cleared_segments=sorted(state.cleared_segments),
        released_rewards=sorted(state.released_rewards),
        trophies=sorted(trophies),
        question=question,
    )


async def _publish(run_id: int, outcome) -> None:
    channel = player_channel(run_id)
    await hub.broadcast(channel, RunStateMsg(
        phase=outcome.state.phase.value,
        segment=outcome.state.segment,
        difficulty=outcome.state.difficulty.value if outcome.state.difficulty else None,
        cleared_segments=sorted(outcome.state.cleared_segments),
        released_rewards=sorted(outcome.state.released_rewards),
    ))
    for trophy in outcome.trophies:
        await hub.broadcast(channel, TrophyPopMsg(
            trophy_id=trophy.id, name=trophy.name, grade=trophy.grade
        ))


@router.get("", response_model=RunView)
async def read_run(
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> RunView:
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    return await _view(service, run, state)


@router.post("/activate", response_model=RunView)
async def activate(
    body: ActivateRequest,
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> RunView:
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    verdict = await service._gates.submit(run.id, GateId.ACTIVATION, body.code)
    if verdict is not GateOutcome.OK:
        raise HTTPException(status.HTTP_403_FORBIDDEN, verdict.value)
    outcome = await service.apply(run, state, Event.ACTIVATED)
    return await _view(service, run, outcome.state)


def _simple(event: Event, path: str):
    @router.post(path, response_model=RunView, name=f"run_{event.value}")
    async def handler(
        request: Request,
        session: SessionData = Depends(require_player),
        settings: Settings = Depends(get_settings),
    ) -> RunView:
        service = build_service(request, settings)
        run, state = await service.load(session.account_id)
        outcome = await service.apply(run, state, event)
        await _publish(run.id, outcome)
        return await _view(service, run, outcome.state)

    return handler


_simple(Event.PROFILE_CHOSEN, "/profile")
_simple(Event.INSTALLED, "/installed")
_simple(Event.HOWTO_ACKED, "/howto")


@router.post("/difficulty", response_model=RunView)
async def choose_difficulty(
    body: DifficultyRequest,
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> RunView:
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    outcome = await service.apply(run, state, Event.DIFFICULTY_CHOSEN, difficulty=body.difficulty)
    await _publish(run.id, outcome)
    return await _view(service, run, outcome.state)


class SegmentBriefView(BaseModel):
    segment: int
    token: str
    seed: str
    mechanic: str
    params: dict[str, float]


@router.post("/segment/start", response_model=SegmentBriefView)
async def start_segment(
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> SegmentBriefView:
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    if state.phase is not Phase.GAME:
        raise HTTPException(status.HTTP_409_CONFLICT, "not at a game")
    brief = await service.start_segment(run, state)
    return SegmentBriefView(**brief.__dict__)


@router.post("/segment/game", response_model=RunView)
async def submit_game(
    body: GameSubmission,
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> RunView:
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    try:
        outcome = await service.submit_game(
            run, state, body.token, GameResult(**body.result.model_dump())
        )
    except TokenInvalid as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await _publish(run.id, outcome)
    return await _view(service, run, outcome.state)


@router.post("/segment/answer", response_model=RunView)
async def submit_answer(
    body: AnswerRequest,
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> RunView:
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    if state.phase is not Phase.QUESTION:
        raise HTTPException(status.HTTP_409_CONFLICT, "not at a question")
    outcome = await service.submit_answer(run, state, body.choice)
    await _publish(run.id, outcome)
    return await _view(service, run, outcome.state)


class CheckpointResponse(BaseModel):
    outcome: str
    attempts_remaining: int | None
    released: CodeReleasedMsg | None
    run: RunView


@router.post("/checkpoint", response_model=CheckpointResponse)
async def submit_checkpoint(
    body: CheckpointRequest,
    request: Request,
    session: SessionData = Depends(require_player),
    settings: Settings = Depends(get_settings),
) -> CheckpointResponse:
    service = build_service(request, settings)
    run, state = await service.load(session.account_id)
    if state.phase is not Phase.CHECKPOINT:
        raise HTTPException(status.HTTP_409_CONFLICT, "not at a checkpoint")

    approved = bool(getattr(request.app.state, "auto_approve_releases", False)) or bool(
        getattr(request.app.state, "release_approved", {}).get(run.id)
    )
    verdict, outcome = await service.submit_checkpoint(run, state, body.code, approved=approved)

    if outcome is None:
        act = (state.segment - 1) // service.shape.segments_per_act + 1
        gate = GateId.CHECKPOINT_1 if act == 1 else GateId.CHECKPOINT_2
        return CheckpointResponse(
            outcome=verdict.value,
            attempts_remaining=await service._gates.attempts_remaining(run.id, gate),
            released=None,
            run=await _view(service, run, state),
        )

    await _publish(run.id, outcome)
    if outcome.released:
        await hub.broadcast(player_channel(run.id), outcome.released)
    return CheckpointResponse(
        outcome=verdict.value,
        attempts_remaining=None,
        released=outcome.released,
        run=await _view(service, run, outcome.state),
    )
```

Move `GameResultBody` above `GameSubmission` in the file so the forward reference resolves.

- [ ] **Step 5: Mount the router in `create_app()`**

```python
from xxvi.api import auth_routes, run_routes
...
    app.include_router(run_routes.router)
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `cd server && pytest tests/test_api_run.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Run the whole backend suite**

Run: `cd server && pytest -v`
Expected: PASS — all tests from Tasks 1–12

- [ ] **Step 8: Commit**

```bash
git add server/xxvi/api server/tests/test_api_run.py server/tests/paths.py server/xxvi/main.py
git commit -m "feat: add run service and player routes with end-to-end coverage"
```

---

## Task 13: Operator routes, WebSocket endpoints, and the CLI fallback

The operator dashboard must never be the only way to release a code.

**Files:**
- Create: `server/xxvi/api/operator_routes.py`, `server/xxvi/api/ws_routes.py`, `server/xxvi/cli.py`
- Modify: `server/xxvi/main.py` (mount routers)
- Test: `server/tests/test_api_operator.py`

**Interfaces:**
- Consumes: `require_operator` (Task 11); `RunService` (Task 12); `hub` (Task 10); `VaultService` (Task 8); `GateService` (Task 7)
- Produces: `POST /api/operator/approve {run_id, reward_id}`, `POST /api/operator/toast {run_id, text}`, `POST /api/operator/unlock-gate {run_id, gate}`, `POST /api/operator/force-golive`, `GET /api/operator/state`. WebSockets `GET /api/ws/player`, `GET /api/ws/operator`. CLI commands `hash-secret`, `release`, `state`.

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/test_api_operator.py
import pytest
from httpx import ASGITransport, AsyncClient

from xxvi.auth.passwords import hash_password
from xxvi.core.models import Difficulty
from xxvi.main import create_app, seed_accounts
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import Settings, get_settings


@pytest.fixture
def settings():
    return Settings(
        player_username="him", player_password_hash=hash_password("pw"),
        operator_username="me", operator_password_hash=hash_password("pw"),
        checkpoint_1_hash=hash_password("X"), reward_1_code="R1",
        go_live_iso="2030-01-01T00:00:00+05:30",  # not yet live
    )


@pytest.fixture
async def app(sessionmaker, settings):
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    application.state.sessionmaker = sessionmaker
    await seed_accounts(sessionmaker, settings)
    return application


@pytest.fixture
async def operator(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/auth/login", json={"username": "me", "password": "pw"})
        yield c


@pytest.fixture
async def player_run(sessionmaker):
    from xxvi.persistence.models import Account
    async with sessionmaker() as session:
        result = await session.execute(
            __import__("sqlalchemy").select(Account).where(Account.username == "him")
        )
        account = result.scalar_one()
    return await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)


async def test_a_player_cannot_reach_operator_routes(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
        assert (await c.post("/api/operator/force-golive")).status_code == 403


async def test_an_anonymous_visitor_cannot_reach_operator_routes(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/api/operator/force-golive")).status_code == 401


async def test_force_golive_opens_the_gate(operator, app):
    assert (await operator.get("/api/session")).json()["live"] is False
    await operator.post("/api/operator/force-golive")
    assert (await operator.get("/api/session")).json()["live"] is True


async def test_approving_a_release_returns_the_code_once(operator, player_run):
    first = await operator.post(
        "/api/operator/approve", json={"run_id": player_run.id, "reward_id": 1}
    )
    assert first.status_code == 200
    assert first.json()["code"] == "R1"

    second = await operator.post(
        "/api/operator/approve", json={"run_id": player_run.id, "reward_id": 1}
    )
    assert second.status_code == 409


async def test_clearing_a_lockout_restores_attempts(operator, player_run, sessionmaker, settings):
    from xxvi.gates.service import GateId, GateOutcome, GateService

    service = GateService(RunRepository(sessionmaker), settings)
    for _ in range(3):
        await service.submit(player_run.id, GateId.CHECKPOINT_1, "wrong")
    assert await service.submit(player_run.id, GateId.CHECKPOINT_1, "X") is GateOutcome.LOCKED

    response = await operator.post(
        "/api/operator/unlock-gate", json={"run_id": player_run.id, "gate": "checkpoint_1"}
    )
    assert response.status_code == 200
    assert await service.submit(player_run.id, GateId.CHECKPOINT_1, "X") is GateOutcome.OK


async def test_operator_state_reports_the_run(operator, player_run):
    body = (await operator.get("/api/operator/state")).json()
    assert body["runs"][0]["id"] == player_run.id
    assert body["runs"][0]["difficulty"] == "kiddie"
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd server && pytest tests/test_api_operator.py -v`
Expected: FAIL — 404s, because the operator router does not exist

- [ ] **Step 3: Write `server/xxvi/api/operator_routes.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from xxvi.api.deps import require_operator
from xxvi.gates.service import GateId, GateService
from xxvi.persistence.models import Run
from xxvi.persistence.repositories import RunRepository
from xxvi.realtime.hub import hub, player_channel
from xxvi.realtime.messages import CodeReleasedMsg, ToastMsg
from xxvi.settings import Settings, get_settings
from xxvi.vault.service import AlreadyReleased, NotApproved, VaultService

router = APIRouter(prefix="/api/operator", dependencies=[Depends(require_operator)])


class ApproveRequest(BaseModel):
    run_id: int
    reward_id: int


class ToastRequest(BaseModel):
    run_id: int
    text: str


class UnlockGateRequest(BaseModel):
    run_id: int
    gate: GateId


class RunSummary(BaseModel):
    id: int
    difficulty: str | None
    phase: str
    segment: int
    cleared_segments: list[int]
    released_rewards: list[int]


class OperatorState(BaseModel):
    live_forced: bool
    runs: list[RunSummary]


@router.post("/approve", response_model=CodeReleasedMsg)
async def approve_release(
    body: ApproveRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> CodeReleasedMsg:
    vault = VaultService(request.app.state.sessionmaker, settings)
    try:
        code = await vault.release(body.run_id, body.reward_id, approved_by_operator=True)
    except AlreadyReleased:
        raise HTTPException(status.HTTP_409_CONFLICT, "already released") from None
    except NotApproved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not approved") from None

    message = CodeReleasedMsg(reward_id=body.reward_id, label=f"Reward {body.reward_id}", code=code)
    await hub.broadcast(player_channel(body.run_id), message)
    return message


@router.post("/toast")
async def send_toast(body: ToastRequest) -> dict[str, int]:
    delivered = await hub.broadcast(player_channel(body.run_id), ToastMsg(text=body.text))
    return {"delivered": delivered}


@router.post("/unlock-gate")
async def unlock_gate(
    body: UnlockGateRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    repo = RunRepository(request.app.state.sessionmaker)
    await GateService(repo, settings).clear_lock(body.run_id, body.gate)
    return {"ok": True}


@router.post("/force-golive")
async def force_golive(request: Request) -> dict[str, bool]:
    request.app.state.force_unlocked = True
    return {"live": True}


@router.get("/state", response_model=OperatorState)
async def operator_state(request: Request) -> OperatorState:
    async with request.app.state.sessionmaker() as session:
        rows = (await session.execute(select(Run))).scalars().all()
    return OperatorState(
        live_forced=bool(getattr(request.app.state, "force_unlocked", False)),
        runs=[
            RunSummary(
                id=r.id, difficulty=r.difficulty, phase=r.phase, segment=r.segment,
                cleared_segments=r.cleared_segments or [],
                released_rewards=r.released_rewards or [],
            )
            for r in rows
        ],
    )
```

- [ ] **Step 4: Write `server/xxvi/api/ws_routes.py`**

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from xxvi.auth.sessions import SESSION_COOKIE, read_session
from xxvi.persistence.repositories import RunRepository
from xxvi.realtime.hub import OPERATOR_CHANNEL, hub, player_channel
from xxvi.realtime.messages import OperatorPresenceMsg

router = APIRouter(prefix="/api/ws")


async def _authenticate(websocket: WebSocket, expected_role: str):
    token = websocket.cookies.get(SESSION_COOKIE)
    session = read_session(token) if token else None
    if session is None or session.role != expected_role:
        await websocket.close(code=4401)
        return None
    await websocket.accept()
    return session


@router.websocket("/player")
async def player_socket(websocket: WebSocket) -> None:
    session = await _authenticate(websocket, "player")
    if session is None:
        return

    repo = RunRepository(websocket.app.state.sessionmaker)
    run = await repo.get_by_account(session.account_id)
    if run is None:
        await websocket.close(code=4404)
        return

    channel = player_channel(run.id)
    await hub.connect(channel, websocket)
    await websocket.send_json(OperatorPresenceMsg(online=hub.operator_online()).model_dump())
    try:
        while True:
            await websocket.receive_text()  # client sends heartbeats only
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(channel, websocket)


@router.websocket("/operator")
async def operator_socket(websocket: WebSocket) -> None:
    session = await _authenticate(websocket, "operator")
    if session is None:
        return

    await hub.connect(OPERATOR_CHANNEL, websocket)
    # Tell every connected player that the operator has arrived.
    for channel in list(hub._channels):  # noqa: SLF001 — single-process hub
        if channel.startswith("player:"):
            await hub.broadcast(channel, OperatorPresenceMsg(online=True))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(OPERATOR_CHANNEL, websocket)
        for channel in list(hub._channels):  # noqa: SLF001
            if channel.startswith("player:"):
                await hub.broadcast(channel, OperatorPresenceMsg(online=hub.operator_online()))
```

- [ ] **Step 5: Write `server/xxvi/cli.py`**

The dashboard-independent release path from spec §8.

```python
"""Operational fallback. If the dashboard is broken, this still releases a code.

    python -m xxvi.cli hash-secret
    python -m xxvi.cli release --run 1 --reward 1
    python -m xxvi.cli state
"""

import argparse
import asyncio
import getpass

from sqlalchemy import select

from xxvi.auth.passwords import hash_password
from xxvi.persistence.models import Run
from xxvi.persistence.session import get_sessionmaker
from xxvi.settings import get_settings
from xxvi.vault.service import AlreadyReleased, VaultService


def cmd_hash_secret() -> None:
    plain = getpass.getpass("secret (will be uppercased and stripped): ")
    print(hash_password(plain.strip().upper()))


async def cmd_release(run_id: int, reward_id: int) -> None:
    vault = VaultService(get_sessionmaker(), get_settings())
    try:
        code = await vault.release(run_id, reward_id, approved_by_operator=True)
    except AlreadyReleased:
        print(f"reward {reward_id} was already released for run {run_id}")
        return
    print(code)


async def cmd_state() -> None:
    async with get_sessionmaker()() as session:
        for run in (await session.execute(select(Run))).scalars():
            print(f"run={run.id} phase={run.phase} segment={run.segment} "
                  f"difficulty={run.difficulty} released={run.released_rewards}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="xxvi")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hash-secret")
    release = sub.add_parser("release")
    release.add_argument("--run", type=int, required=True)
    release.add_argument("--reward", type=int, required=True)
    sub.add_parser("state")

    args = parser.parse_args()
    match args.command:
        case "hash-secret":
            cmd_hash_secret()
        case "release":
            asyncio.run(cmd_release(args.run, args.reward))
        case "state":
            asyncio.run(cmd_state())


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Mount both routers in `create_app()`**

```python
from xxvi.api import auth_routes, operator_routes, run_routes, ws_routes
...
    app.include_router(operator_routes.router)
    app.include_router(ws_routes.router)
```

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `cd server && pytest tests/test_api_operator.py -v`
Expected: PASS (6 tests)

- [ ] **Step 8: Verify the CLI works against a real database**

Run: `cd server && python -m xxvi.cli state`
Expected: prints one line per run, or nothing if there are none. No traceback.

- [ ] **Step 9: Commit**

```bash
git add server/xxvi/api server/xxvi/cli.py server/tests/test_api_operator.py server/xxvi/main.py
git commit -m "feat: add operator routes, websocket endpoints and CLI release fallback"
```

---

## Task 14: Frontend scaffold, generated types, API and WS clients

**Files:**
- Create: `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/index.html`, `web/src/main.tsx`, `web/src/App.tsx`
- Create: `web/src/lib/client.ts`, `web/src/lib/ws.ts`, `web/src/ws-messages.ts`
- Test: `web/tests/ws.test.ts`

**Interfaces:**
- Consumes: the running backend's `/api/openapi.json`
- Produces: `api.ts` (generated); `api` client object with `getSession()`, `login(u,p)`, `logout()`, `getRun()`, `activate(code)`, `chooseProfile()`, `chooseDifficulty(d)`, `installed()`, `ackHowto()`, `startSegment()`, `submitGame(token, result)`, `submitAnswer(choice)`, `submitCheckpoint(code)`; `ServerMessage` TS union mirroring `realtime/messages.py`; `connect(path, handlers)` returning `{ close }` with automatic reconnect.

- [ ] **Step 1: Scaffold the app**

```bash
cd web
npm create vite@latest . -- --template react-ts
npm install
npm install -D openapi-typescript vitest jsdom @testing-library/react @testing-library/jest-dom
```

Add to `web/package.json` scripts:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "codegen": "openapi-typescript http://localhost:8000/api/openapi.json -o src/api.ts"
  }
}
```

Add a dev proxy to `web/vite.config.ts` so cookies work on one origin:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true, ws: true },
    },
  },
  test: { environment: "jsdom", globals: true },
});
```

- [ ] **Step 2: Generate the API types**

With the backend running (`cd server && uvicorn xxvi.main:app --reload`):

Run: `cd web && npm run codegen`
Expected: `web/src/api.ts` is written. Add a banner comment at the top by hand — the file is a build artifact and must never be edited:

```ts
// GENERATED by `npm run codegen` from the backend's OpenAPI schema.
// Do not edit. Change the Pydantic model and regenerate.
```

- [ ] **Step 3: Write `web/src/ws-messages.ts`**

The hand-written mirror of `server/xxvi/realtime/messages.py`. Every message type lives here and nowhere else on this side.

```ts
// MIRRORS server/xxvi/realtime/messages.py — keep the two files in step.
export type RunStateMsg = {
  type: "run_state";
  phase: string;
  segment: number;
  difficulty: string | null;
  cleared_segments: number[];
  released_rewards: number[];
};

export type TrophyPopMsg = {
  type: "trophy_pop";
  trophy_id: string;
  name: string;
  grade: "bronze" | "silver" | "gold" | "platinum";
};

export type CodeReleasedMsg = {
  type: "code_released";
  reward_id: number;
  label: string;
  code: string;
};

export type ToastMsg = { type: "toast"; text: string };
export type OperatorPresenceMsg = { type: "operator_presence"; online: boolean };
export type GateResultMsg = {
  type: "gate_result";
  gate: string;
  outcome: string;
  attempts_remaining: number | null;
};

export type ServerMessage =
  | RunStateMsg
  | TrophyPopMsg
  | CodeReleasedMsg
  | ToastMsg
  | OperatorPresenceMsg
  | GateResultMsg;
```

- [ ] **Step 4: Write `web/src/lib/client.ts`**

```ts
export type GameResultPayload = {
  mechanic: string;
  passed_client_side: boolean;
  duration_ms: number;
  input_count: number;
  score: number;
  sequence: number[];
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw Object.assign(new Error(`${response.status} ${path}`), {
      status: response.status,
    });
  }
  return (await response.json()) as T;
}

const post = <T,>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });

export const api = {
  getSession: () => call<SessionInfo>("/api/session"),
  login: (username: string, password: string) =>
    post<{ role: string }>("/api/auth/login", { username, password }),
  logout: () => post<{ ok: boolean }>("/api/auth/logout"),

  getRun: () => call<RunView>("/api/run"),
  activate: (code: string) => post<RunView>("/api/run/activate", { code }),
  chooseProfile: () => post<RunView>("/api/run/profile"),
  chooseDifficulty: (difficulty: "kiddie" | "devil") =>
    post<RunView>("/api/run/difficulty", { difficulty }),
  installed: () => post<RunView>("/api/run/installed"),
  ackHowto: () => post<RunView>("/api/run/howto"),

  startSegment: () => post<SegmentBrief>("/api/run/segment/start"),
  submitGame: (token: string, result: GameResultPayload) =>
    post<RunView>("/api/run/segment/game", { token, result }),
  submitAnswer: (choice: number) => post<RunView>("/api/run/segment/answer", { choice }),
  submitCheckpoint: (code: string) => post<CheckpointResponse>("/api/run/checkpoint", { code }),
};

export type SessionInfo = {
  authenticated: boolean;
  role: string | null;
  live: boolean;
  seconds_until_live: number;
};

export type QuestionView = { prompt: string; choices: string[] };

export type RunView = {
  phase: string;
  segment: number;
  difficulty: string | null;
  cleared_segments: number[];
  released_rewards: number[];
  trophies: string[];
  question: QuestionView | null;
};

export type SegmentBrief = {
  segment: number;
  token: string;
  seed: string;
  mechanic: string;
  params: Record<string, number>;
};

export type CheckpointResponse = {
  outcome: "ok" | "wrong" | "locked";
  attempts_remaining: number | null;
  released: { reward_id: number; label: string; code: string } | null;
  run: RunView;
};
```

- [ ] **Step 5: Write the failing test for the WS client**

```ts
// web/tests/ws.test.ts
import { describe, expect, it, vi } from "vitest";
import { connect } from "../src/lib/ws";

class FakeSocket {
  static instances: FakeSocket[] = [];
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onopen: (() => void) | null = null;
  readyState = 1;
  sent: string[] = [];
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  send(data: string) { this.sent.push(data); }
  close() { this.readyState = 3; this.onclose?.(); }
}

describe("connect", () => {
  it("routes messages to the handler matching their type", () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    const onTrophy = vi.fn();
    const onToast = vi.fn();
    connect("/api/ws/player", { trophy_pop: onTrophy, toast: onToast });

    const socket = FakeSocket.instances.at(-1)!;
    socket.onmessage?.({ data: JSON.stringify({ type: "toast", text: "bro" }) });

    expect(onToast).toHaveBeenCalledWith({ type: "toast", text: "bro" });
    expect(onTrophy).not.toHaveBeenCalled();
  });

  it("ignores message types with no handler", () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    connect("/api/ws/player", {});
    const socket = FakeSocket.instances.at(-1)!;
    expect(() =>
      socket.onmessage?.({ data: JSON.stringify({ type: "run_state" }) }),
    ).not.toThrow();
  });

  it("reconnects after the socket closes", async () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    const before = FakeSocket.instances.length;
    connect("/api/ws/player", {}, { retryMs: 1 });
    FakeSocket.instances.at(-1)!.close();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(FakeSocket.instances.length).toBeGreaterThan(before + 1);
  });
});
```

- [ ] **Step 6: Run it and confirm it fails**

Run: `cd web && npm test`
Expected: FAIL — cannot resolve `../src/lib/ws`

- [ ] **Step 7: Write `web/src/lib/ws.ts`**

```ts
import type { ServerMessage } from "../ws-messages";

type Handlers = {
  [K in ServerMessage["type"]]?: (message: Extract<ServerMessage, { type: K }>) => void;
};

type Options = { retryMs?: number };

export function connect(path: string, handlers: Handlers, options: Options = {}) {
  const retryMs = options.retryMs ?? 2000;
  let socket: WebSocket | null = null;
  let closedByUs = false;
  let heartbeat: ReturnType<typeof setInterval> | undefined;

  const open = () => {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${location.host}${path}`);

    socket.onopen = () => {
      heartbeat = setInterval(() => socket?.send("ping"), 25_000);
    };

    socket.onmessage = (event) => {
      const message = JSON.parse(event.data) as ServerMessage;
      const handler = handlers[message.type] as ((m: ServerMessage) => void) | undefined;
      handler?.(message);
    };

    socket.onclose = () => {
      clearInterval(heartbeat);
      // The run lives on the server. A dropped socket is cosmetic — reconnect
      // quietly and let the next poll or message resync state.
      if (!closedByUs) setTimeout(open, retryMs);
    };
  };

  open();

  return {
    close() {
      closedByUs = true;
      clearInterval(heartbeat);
      socket?.close();
    },
  };
}
```

- [ ] **Step 8: Run the tests and confirm they pass**

Run: `cd web && npm test`
Expected: PASS (3 tests)

- [ ] **Step 9: Commit**

```bash
git add web
git commit -m "feat: scaffold frontend with generated API types and reconnecting WS client"
```

---

## Task 15: Coming-soon page, login, and the server-driven countdown

**Files:**
- Create: `web/src/ComingSoon.tsx`, `web/src/Login.tsx`, `web/src/lib/countdown.ts`
- Modify: `web/src/App.tsx`
- Test: `web/tests/countdown.test.ts`, `web/tests/comingsoon.test.tsx`

**Interfaces:**
- Consumes: `api.getSession`, `api.login` (Task 14)
- Produces: `formatCountdown(seconds) -> string`; `<ComingSoon session copy />`; `<Login onSuccess />`; `App` routing on `{authenticated, role, live}`.

- [ ] **Step 1: Write the failing countdown test**

The client renders a countdown but never decides whether the gate is open — that verdict is always the server's.

```ts
// web/tests/countdown.test.ts
import { describe, expect, it } from "vitest";
import { formatCountdown } from "../src/lib/countdown";

describe("formatCountdown", () => {
  it("renders days, hours, minutes and seconds", () => {
    expect(formatCountdown(2 * 86400 + 3 * 3600 + 4 * 60 + 5)).toBe("02:03:04:05");
  });
  it("pads single digits", () => {
    expect(formatCountdown(61)).toBe("00:00:01:01");
  });
  it("floors at zero and never goes negative", () => {
    expect(formatCountdown(0)).toBe("00:00:00:00");
    expect(formatCountdown(-500)).toBe("00:00:00:00");
  });
});
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd web && npm test countdown`
Expected: FAIL — cannot resolve `../src/lib/countdown`

- [ ] **Step 3: Write `web/src/lib/countdown.ts`**

```ts
const pad = (value: number) => String(value).padStart(2, "0");

/** Formats a server-supplied remaining-seconds value. The client's own clock
 *  is used only to tick this number down between polls, never to decide
 *  whether the gate is open. */
export function formatCountdown(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return [days, hours, minutes, seconds % 60].map(pad).join(":");
}
```

- [ ] **Step 4: Write `web/src/ComingSoon.tsx`**

High contrast and large type, because this is viewed through a lossy codec.

```tsx
import { useEffect, useState } from "react";
import { formatCountdown } from "./lib/countdown";
import type { SessionInfo } from "./lib/client";

type Props = { session: SessionInfo; copy: string; teaser: string };

export function ComingSoon({ session, copy, teaser }: Props) {
  const [remaining, setRemaining] = useState(session.seconds_until_live);

  useEffect(() => {
    setRemaining(session.seconds_until_live);
    const tick = setInterval(() => setRemaining((n) => Math.max(0, n - 1)), 1000);
    return () => clearInterval(tick);
  }, [session.seconds_until_live]);

  const personalised = session.authenticated && session.role === "player";

  return (
    <main className="coming-soon">
      <p className="coming-soon__copy">{personalised ? teaser : copy}</p>
      {personalised && (
        <p className="coming-soon__countdown" aria-label="time remaining">
          {formatCountdown(remaining)}
        </p>
      )}
    </main>
  );
}
```

- [ ] **Step 5: Write the failing component test**

```tsx
// web/tests/comingsoon.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ComingSoon } from "../src/ComingSoon";

const base = { authenticated: false, role: null, live: false, seconds_until_live: 90 };

describe("ComingSoon", () => {
  it("shows generic copy and no countdown to anonymous visitors", () => {
    render(<ComingSoon session={base} copy="generic" teaser="personal" />);
    expect(screen.getByText("generic")).toBeDefined();
    expect(screen.queryByLabelText("time remaining")).toBeNull();
  });

  it("shows the teaser and a countdown once he is signed in", () => {
    render(
      <ComingSoon
        session={{ ...base, authenticated: true, role: "player" }}
        copy="generic"
        teaser="personal"
      />,
    );
    expect(screen.getByText("personal")).toBeDefined();
    expect(screen.getByLabelText("time remaining").textContent).toBe("00:00:01:30");
  });

  it("never reveals the structure of what is coming", () => {
    const { container } = render(<ComingSoon session={base} copy="generic" teaser="personal" />);
    const text = container.textContent ?? "";
    for (const leak of ["trophy", "segment", "act", "XXVI", "platinum"]) {
      expect(text.toLowerCase()).not.toContain(leak.toLowerCase());
    }
  });
});
```

Add `web/tests/setup.ts` with `import "@testing-library/jest-dom";` and reference it from `vite.config.ts` via `test: { setupFiles: ["./tests/setup.ts"] }`.

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `cd web && npm test`
Expected: PASS (countdown + coming-soon + ws tests)

- [ ] **Step 7: Write `web/src/Login.tsx` and wire `App.tsx`**

```tsx
import { useState } from "react";
import { api } from "./lib/client";

export function Login({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await api.login(username, password);
      onSuccess();
    } catch {
      setError("nope");
    }
  };

  return (
    <form onSubmit={submit} className="login">
      <label>
        user
        <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
      </label>
      <label>
        pass
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      <button type="submit">sign in</button>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
```

```tsx
// web/src/App.tsx
import { useCallback, useEffect, useState } from "react";
import { ComingSoon } from "./ComingSoon";
import { Login } from "./Login";
import { api, type SessionInfo } from "./lib/client";

export default function App() {
  const [session, setSession] = useState<SessionInfo | null>(null);

  const refresh = useCallback(async () => setSession(await api.getSession()), []);
  useEffect(() => {
    void refresh();
    const poll = setInterval(refresh, 30_000);
    return () => clearInterval(poll);
  }, [refresh]);

  if (!session) return null;

  if (!session.live || !session.authenticated) {
    return (
      <>
        <ComingSoon session={session} copy="…" teaser="…" />
        {!session.authenticated && <Login onSuccess={refresh} />}
      </>
    );
  }

  if (session.role === "operator") return <div>operator dashboard — Task 21</div>;
  return <div>console — Task 16</div>;
}
```

Copy strings come from `GET /api/content` (Task 11b). Fetch it alongside the session in `App.tsx` and pass `content.copy.coming_soon` and `content.copy.teaser` into `<ComingSoon />` — never hardcode copy in a component.

- [ ] **Step 8: Commit**

```bash
git add web
git commit -m "feat: add coming-soon page, login and server-driven countdown"
```

---

## Task 16: Console shell — boot, fullscreen, activation, profile, difficulty, install, how-to-play

**Files:**
- Create: `web/src/lib/fullscreen.ts`, `web/src/shell/Boot.tsx`, `web/src/shell/Activation.tsx`, `web/src/shell/ProfileSelect.tsx`, `web/src/shell/DifficultySelect.tsx`, `web/src/shell/Install.tsx`, `web/src/shell/HowToPlay.tsx`, `web/src/Console.tsx`, `web/src/console.css`
- Test: `web/tests/fullscreen.test.ts`, `web/tests/shell.test.tsx`

**Interfaces:**
- Consumes: `api` (Task 14), `connect` (Task 14)
- Produces: `requestFullscreen(element) -> Promise<boolean>` (never throws), `isFullscreen() -> boolean`; shell components each taking `{ onDone }`; `<Console />` dispatching on `RunView.phase`.

- [ ] **Step 1: Write the failing fullscreen test**

Fullscreen is an enhancement. A rejection must never surface as an error.

```ts
// web/tests/fullscreen.test.ts
import { describe, expect, it, vi } from "vitest";
import { requestFullscreen } from "../src/lib/fullscreen";

describe("requestFullscreen", () => {
  it("returns true when the browser grants it", async () => {
    const element = { requestFullscreen: vi.fn().mockResolvedValue(undefined) };
    expect(await requestFullscreen(element as unknown as HTMLElement)).toBe(true);
  });

  it("returns false instead of throwing when the browser refuses", async () => {
    const element = { requestFullscreen: vi.fn().mockRejectedValue(new Error("denied")) };
    expect(await requestFullscreen(element as unknown as HTMLElement)).toBe(false);
  });

  it("returns false when the API is missing entirely", async () => {
    expect(await requestFullscreen({} as HTMLElement)).toBe(false);
  });
});
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd web && npm test fullscreen`
Expected: FAIL — cannot resolve `../src/lib/fullscreen`

- [ ] **Step 3: Write `web/src/lib/fullscreen.ts`**

```ts
/** Fullscreen is an enhancement and must never block anything.
 *  Requires a user gesture, so this is only ever called from a click handler.
 *  Esc exits and that is not overridable — so nothing in the app binds Esc. */
export async function requestFullscreen(element: HTMLElement): Promise<boolean> {
  if (typeof element.requestFullscreen !== "function") return false;
  try {
    await element.requestFullscreen();
    return true;
  } catch {
    return false;
  }
}

export function isFullscreen(): boolean {
  return typeof document !== "undefined" && document.fullscreenElement !== null;
}

export function onFullscreenChange(handler: (active: boolean) => void): () => void {
  const listener = () => handler(isFullscreen());
  document.addEventListener("fullscreenchange", listener);
  return () => document.removeEventListener("fullscreenchange", listener);
}
```

- [ ] **Step 4: Write `web/src/shell/Boot.tsx`**

The fullscreen request rides the power-on click — framed as part of booting, not as a browser setting.

```tsx
import { useState } from "react";
import { requestFullscreen } from "../lib/fullscreen";

export function Boot({ onDone }: { onDone: () => void }) {
  const [booting, setBooting] = useState(false);

  const powerOn = async () => {
    setBooting(true);
    await requestFullscreen(document.documentElement); // may be refused; we continue either way
    setTimeout(onDone, 2200);
  };

  return (
    <main className={`boot ${booting ? "boot--on" : ""}`}>
      {!booting ? (
        <button className="boot__power" onClick={powerOn} autoFocus>
          press to power on
        </button>
      ) : (
        <div className="boot__logo" aria-label="powering on" />
      )}
    </main>
  );
}
```

- [ ] **Step 5: Write `web/src/shell/Activation.tsx`**

```tsx
import { useState } from "react";
import { api } from "../lib/client";

const KEY_PATTERN = /^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/;

export function Activation({ onDone }: { onDone: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.activate(value.trim().toUpperCase());
      onDone();
    } catch {
      // The front door is rate-limited but never hard-locks. Always let him retry.
      setError("that key isn't valid");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="activation" onSubmit={submit}>
      <h1>enter product key</h1>
      <input
        className="activation__input"
        value={value}
        onChange={(e) => setValue(e.target.value.toUpperCase())}
        placeholder="XXXX-XXXX-XXXX"
        aria-label="product key"
        autoFocus
      />
      <button type="submit" disabled={busy || !KEY_PATTERN.test(value.trim())}>
        activate
      </button>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
```

- [ ] **Step 6: Write the remaining shell screens**

```tsx
// web/src/shell/ProfileSelect.tsx
import { api } from "../lib/client";

export function ProfileSelect({ onDone, operatorOnline }: { onDone: () => void; operatorOnline: boolean }) {
  return (
    <section className="profiles">
      <h1>who's using the console?</h1>
      <div className="profiles__row">
        <button className="profile" onClick={async () => { await api.chooseProfile(); onDone(); }} autoFocus>
          <span className="profile__avatar" />
          <span className="profile__name">him</span>
        </button>
        <div className={`profile profile--other ${operatorOnline ? "is-online" : ""}`} aria-live="polite">
          <span className="profile__avatar" />
          <span className="profile__name">kritish</span>
          <span className="profile__status">{operatorOnline ? "online" : "offline"}</span>
        </div>
      </div>
    </section>
  );
}
```

```tsx
// web/src/shell/DifficultySelect.tsx
import { useState } from "react";
import { api } from "../lib/client";

export function DifficultySelect({ onDone }: { onDone: () => void }) {
  const [hovered, setHovered] = useState<"kiddie" | "devil">("kiddie");

  const choose = async (difficulty: "kiddie" | "devil") => {
    await api.chooseDifficulty(difficulty);
    onDone();
  };

  return (
    <section className={`difficulty difficulty--${hovered}`}>
      <h1>select difficulty</h1>
      <button onMouseEnter={() => setHovered("kiddie")} onFocus={() => setHovered("kiddie")}
              onClick={() => choose("kiddie")} autoFocus>
        <strong>KIDDIE</strong>
        <span>a fail costs you the current segment</span>
      </button>
      <button onMouseEnter={() => setHovered("devil")} onFocus={() => setHovered("devil")}
              onClick={() => choose("devil")}>
        <strong>DEVIL</strong>
        <span>a fail costs you everything</span>
      </button>
      <p className="difficulty__note">codes you've already earned are yours. nothing takes those back.</p>
    </section>
  );
}
```

The `install` phase opens on the **library card** — the game he's never seen, sitting at 0%. This is the screen carrying the title and the box art, so it gets its own beat before the progress bar starts. It lives inside `Install` rather than as a new phase, because the state machine is already exhaustively tested and does not need a new state for a screen transition.

The title is never explained. Box art is `X X V I` above a rule with `XX · VI` beneath, and the strapline is *"you've been playing this one since 2006."*

```tsx
// web/src/shell/Install.tsx
import { useEffect, useState } from "react";
import { api } from "../lib/client";

const SUBTITLES = [
  "copying 20 years…",
  "decompressing inside jokes…",
  "verifying trauma…",
  "indexing grudges…",
];

function LibraryCard({ onInstall }: { onInstall: () => void }) {
  return (
    <section className="library">
      <div className="boxart">
        <p className="boxart__title">X X V I</p>
        <hr className="boxart__rule" />
        <p className="boxart__split">XX · VI</p>
      </div>
      <p className="library__progress">0%  ·  0 of 19 trophies</p>
      <p className="library__strapline">you've been playing this one since 2006.</p>
      <button onClick={onInstall} autoFocus>install</button>
    </section>
  );
}

export function Install({ onDone }: { onDone: () => void }) {
  const [installing, setInstalling] = useState(false);
  const [percent, setPercent] = useState(0);

  useEffect(() => {
    if (!installing) return;
    const step = setInterval(() => setPercent((p) => Math.min(100, p + 2)), 100);
    return () => clearInterval(step);
  }, [installing]);

  useEffect(() => {
    if (!installing || percent < 100) return;
    void api.installed().then(onDone);
  }, [installing, percent, onDone]);

  if (!installing) return <LibraryCard onInstall={() => setInstalling(true)} />;

  return (
    <section className="install">
      <h1>installing</h1>
      <div className="install__bar"><div className="install__fill" style={{ width: `${percent}%` }} /></div>
      <p className="install__percent">{percent}%</p>
      <p className="install__subtitle">{SUBTITLES[Math.floor(percent / 26) % SUBTITLES.length]}</p>
    </section>
  );
}
```

```tsx
// web/src/shell/HowToPlay.tsx
import { api } from "../lib/client";

export function HowToPlay({ onDone }: { onDone: () => void }) {
  return (
    <section className="howto">
      <h1>2 acts. 8 trophies of memory. 8 of skill.</h1>
      <p>clear an act, and kritish releases a code.</p>
      <p><strong>KIDDIE</strong> — a fail costs you the current segment.</p>
      <p><strong>DEVIL</strong> — a fail costs you everything.</p>
      <p className="howto__note">codes you've already earned are yours. nothing takes those back.</p>
      <button onClick={async () => { await api.ackHowto(); onDone(); }} autoFocus>start</button>
    </section>
  );
}
```

- [ ] **Step 7: Write `web/src/Console.tsx`**

```tsx
import { useCallback, useEffect, useState } from "react";
import { Activation } from "./shell/Activation";
import { Boot } from "./shell/Boot";
import { DifficultySelect } from "./shell/DifficultySelect";
import { HowToPlay } from "./shell/HowToPlay";
import { Install } from "./shell/Install";
import { ProfileSelect } from "./shell/ProfileSelect";
import { api, type RunView } from "./lib/client";
import { connect } from "./lib/ws";

export function Console() {
  const [run, setRun] = useState<RunView | null>(null);
  const [booted, setBooted] = useState(false);
  const [operatorOnline, setOperatorOnline] = useState(false);

  const refresh = useCallback(async () => setRun(await api.getRun()), []);

  useEffect(() => {
    void refresh();
    const socket = connect("/api/ws/player", {
      run_state: () => void refresh(),
      operator_presence: (m) => setOperatorOnline(m.online),
    });
    // The socket is cosmetic; polling is the safety net if it dies.
    const poll = setInterval(refresh, 15_000);
    return () => { socket.close(); clearInterval(poll); };
  }, [refresh]);

  if (!run) return null;
  if (!booted) return <Boot onDone={() => setBooted(true)} />;

  switch (run.phase) {
    case "activation": return <Activation onDone={refresh} />;
    case "profile": return <ProfileSelect onDone={refresh} operatorOnline={operatorOnline} />;
    case "difficulty": return <DifficultySelect onDone={refresh} />;
    case "install": return <Install onDone={refresh} />;
    case "howto": return <HowToPlay onDone={refresh} />;
    default: return <div>segment {run.segment} — Tasks 18–20</div>;
  }
}
```

- [ ] **Step 8: Write the shell tests**

```tsx
// web/tests/shell.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Activation } from "../src/shell/Activation";
import { ProfileSelect } from "../src/shell/ProfileSelect";

vi.mock("../src/lib/client", () => ({
  api: { activate: vi.fn().mockRejectedValue(new Error("403")), chooseProfile: vi.fn() },
}));

describe("Activation", () => {
  it("refuses to submit until the key is well formed", async () => {
    render(<Activation onDone={vi.fn()} />);
    const button = screen.getByRole("button", { name: "activate" });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText("product key"), "abcd-efgh-ijkl");
    expect(button).not.toBeDisabled();
  });

  it("lets him retry after a rejection — the front door never locks", async () => {
    render(<Activation onDone={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("product key"), "abcd-efgh-ijkl");
    await userEvent.click(screen.getByRole("button", { name: "activate" }));
    expect(await screen.findByRole("alert")).toBeDefined();
    expect(screen.getByRole("button", { name: "activate" })).not.toBeDisabled();
  });
});

describe("ProfileSelect", () => {
  it("shows the operator as offline until the dashboard connects", () => {
    const { rerender } = render(<ProfileSelect onDone={vi.fn()} operatorOnline={false} />);
    expect(screen.getByText("offline")).toBeDefined();
    rerender(<ProfileSelect onDone={vi.fn()} operatorOnline />);
    expect(screen.getByText("online")).toBeDefined();
  });
});
```

Install `@testing-library/user-event` as a dev dependency.

- [ ] **Step 9: Run the tests and confirm they pass**

Run: `cd web && npm test`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add web
git commit -m "feat: add console shell with boot, fullscreen, activation and setup screens"
```

---

## Task 17: Trophy system — pop toast and cabinet

Every pop must read as complete with the sound muted.

**Files:**
- Create: `web/src/shell/TrophyToast.tsx`, `web/src/shell/TrophyCabinet.tsx`, `web/src/lib/sound.ts`
- Test: `web/tests/trophy.test.tsx`

**Interfaces:**
- Consumes: `TrophyPopMsg` (Task 14)
- Produces: `<TrophyToast queue onDismiss />`, `<TrophyCabinet trophies earned closing />`, `playTrophySound(grade)` (no-op when audio is unavailable).

- [ ] **Step 1: Write the failing tests**

```tsx
// web/tests/trophy.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TrophyToast } from "../src/shell/TrophyToast";
import { TrophyCabinet } from "../src/shell/TrophyCabinet";

const pop = { type: "trophy_pop" as const, trophy_id: "game-1", name: "First Blood", grade: "bronze" as const };

describe("TrophyToast", () => {
  it("renders the name and grade as text, not only as sound or colour", () => {
    render(<TrophyToast queue={[pop]} onDismiss={vi.fn()} />);
    expect(screen.getByText("First Blood")).toBeDefined();
    expect(screen.getByText(/bronze/i)).toBeDefined();
  });

  it("shows one trophy at a time when several arrive together", () => {
    render(<TrophyToast queue={[pop, { ...pop, trophy_id: "game-2", name: "Second" }]} onDismiss={vi.fn()} />);
    expect(screen.getByText("First Blood")).toBeDefined();
    expect(screen.queryByText("Second")).toBeNull();
  });
});

describe("TrophyCabinet", () => {
  const trophies = [
    { id: "game-1", name: "First Blood", grade: "bronze", hidden: false },
    { id: "hidden-rage-quit", name: "Rage Quit", grade: "bronze", hidden: true },
    { id: "platinum", name: "XXVI", grade: "platinum", hidden: false },
  ];

  it("masks the name of a hidden trophy that has not popped", () => {
    render(<TrophyCabinet trophies={trophies} earned={["game-1"]} closing="" />);
    expect(screen.queryByText("Rage Quit")).toBeNull();
    expect(screen.getAllByText("???").length).toBe(1);
  });

  it("reveals a hidden trophy once earned", () => {
    render(<TrophyCabinet trophies={trophies} earned={["game-1", "hidden-rage-quit"]} closing="" />);
    expect(screen.getByText("Rage Quit")).toBeDefined();
  });

  it("marks unearned standard trophies as locked without hiding their names", () => {
    render(<TrophyCabinet trophies={trophies} earned={["game-1"]} closing="" />);
    expect(screen.getByText("XXVI").closest("li")).toHaveClass("trophy--locked");
  });
});
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd web && npm test trophy`
Expected: FAIL — cannot resolve the trophy modules

- [ ] **Step 3: Write `web/src/lib/sound.ts`**

```ts
/** Sound is a bonus layer. He may be screen-sharing without system audio,
 *  so nothing may depend on a pop being audible. Failures are swallowed. */
const FILES: Record<string, string> = {
  bronze: "/sfx/pop-bronze.mp3",
  silver: "/sfx/pop-silver.mp3",
  gold: "/sfx/pop-gold.mp3",
  platinum: "/sfx/pop-platinum.mp3",
};

export function playTrophySound(grade: string): void {
  try {
    const file = FILES[grade];
    if (!file || typeof Audio === "undefined") return;
    void new Audio(file).play().catch(() => undefined);
  } catch {
    // deliberately ignored
  }
}
```

- [ ] **Step 4: Write `web/src/shell/TrophyToast.tsx`**

```tsx
import { useEffect } from "react";
import { playTrophySound } from "../lib/sound";
import type { TrophyPopMsg } from "../ws-messages";

type Props = { queue: TrophyPopMsg[]; onDismiss: () => void; holdMs?: number };

export function TrophyToast({ queue, onDismiss, holdMs = 4000 }: Props) {
  const current = queue[0];

  useEffect(() => {
    if (!current) return;
    playTrophySound(current.grade);
    const timer = setTimeout(onDismiss, holdMs);
    return () => clearTimeout(timer);
  }, [current, holdMs, onDismiss]);

  if (!current) return null;

  return (
    <aside className={`toast toast--${current.grade}`} role="status" aria-live="polite">
      <span className={`toast__icon toast__icon--${current.grade}`} />
      <span className="toast__body">
        <strong className="toast__name">{current.name}</strong>
        {/* Grade is written out, not conveyed by colour alone — the stream
            compresses colour far harder than it compresses text. */}
        <span className="toast__grade">{current.grade} trophy unlocked</span>
      </span>
    </aside>
  );
}
```

- [ ] **Step 5: Write `web/src/shell/TrophyCabinet.tsx`**

```tsx
type Trophy = { id: string; name: string; grade: string; hidden: boolean };

type Props = { trophies: Trophy[]; earned: string[]; closing: string };

export function TrophyCabinet({ trophies, earned, closing }: Props) {
  const held = new Set(earned);
  const standard = trophies.filter((t) => !t.hidden);
  const percent = Math.round((standard.filter((t) => held.has(t.id)).length / standard.length) * 100);

  return (
    <section className="cabinet">
      <header className="cabinet__header">
        <h1>trophies</h1>
        <p className="cabinet__percent">{percent}%</p>
      </header>
      <ul className="cabinet__list">
        {trophies.map((trophy) => {
          const owned = held.has(trophy.id);
          const masked = trophy.hidden && !owned;
          return (
            <li key={trophy.id} className={`trophy trophy--${trophy.grade} ${owned ? "" : "trophy--locked"}`}>
              <span className={`trophy__icon trophy__icon--${trophy.grade}`} />
              <span className="trophy__name">{masked ? "???" : trophy.name}</span>
              <span className="trophy__grade">{trophy.grade}</span>
            </li>
          );
        })}
      </ul>
      {closing && <p className="cabinet__closing">{closing}</p>}
    </section>
  );
}
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `cd web && npm test`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add web
git commit -m "feat: add trophy toast and cabinet, legible without sound"
```

---

## Task 18: Game harness and Simon Says

**Files:**
- Create: `web/src/games/types.ts`, `web/src/games/registry.ts`, `web/src/games/SimonSays.tsx`, `web/src/lib/input.ts`, `web/src/games/GameHost.tsx`
- Test: `web/tests/simon.test.tsx`, `web/tests/seq.test.ts`

**Interfaces:**
- Consumes: `SegmentBrief`, `GameResultPayload`, `api.submitGame` (Task 14)
- Produces: `GameProps = { seed: string; params: Record<string, number>; onFinish: (r: GameOutcome) => void }`, `GameOutcome = { passed: boolean; durationMs: number; inputCount: number; score: number; sequence: number[] }`, `GAMES: Record<string, ComponentType<GameProps>>`, `simonSequence(seed, length)` (mirrors `server/xxvi/games/seeds.py`), `FACE_KEYS`, `<GameHost brief onDone />`.

- [ ] **Step 1: Write the failing sequence test**

The client must derive the same sequence the server did, from the same seed. This test is the contract between the two implementations.

```ts
// web/tests/seq.test.ts
import { describe, expect, it } from "vitest";
import { simonSequence } from "../src/games/SimonSays";

describe("simonSequence", () => {
  it("is deterministic for a seed", async () => {
    expect(await simonSequence("seed-a", 6)).toEqual(await simonSequence("seed-a", 6));
  });
  it("differs between seeds", async () => {
    expect(await simonSequence("seed-a", 8)).not.toEqual(await simonSequence("seed-b", 8));
  });
  it("makes a short sequence a prefix of a longer one", async () => {
    const long = await simonSequence("seed-a", 8);
    expect(await simonSequence("seed-a", 4)).toEqual(long.slice(0, 4));
  });
  it("emits only face buttons", async () => {
    expect(new Set(await simonSequence("seed-a", 40)).size).toBeLessThanOrEqual(4);
    for (const value of await simonSequence("seed-a", 40)) {
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThan(4);
    }
  });
  it("matches the sequence the server generates for a known seed", async () => {
    // Pin one vector against `python -c "from xxvi.games.seeds import simon_sequence;
    // print(simon_sequence('pinned', 8))"` and paste the result here.
    expect(await simonSequence("pinned", 8)).toEqual(SERVER_VECTOR);
  });
});

// Replace with the actual output of the Python one-liner above.
const SERVER_VECTOR: number[] = [];
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd web && npm test seq`
Expected: FAIL — cannot resolve `../src/games/SimonSays`

- [ ] **Step 3: Write `web/src/games/types.ts` and `web/src/lib/input.ts`**

```ts
// web/src/games/types.ts
export type GameOutcome = {
  passed: boolean;
  durationMs: number;
  inputCount: number;
  score: number;
  sequence: number[];
};

export type GameProps = {
  seed: string;
  params: Record<string, number>;
  onFinish: (outcome: GameOutcome) => void;
};
```

```ts
// web/src/lib/input.ts
/** Face buttons: 0 triangle, 1 circle, 2 cross, 3 square.
 *  Keyboard is the supported path. Esc is deliberately unbound — it exits
 *  fullscreen and that behaviour is not overridable. */
export const FACE_KEYS: Record<string, number> = {
  KeyW: 0, ArrowUp: 0,
  KeyD: 1, ArrowRight: 1,
  KeyS: 2, ArrowDown: 2,
  KeyA: 3, ArrowLeft: 3,
};

export const FACE_GLYPHS = ["△", "○", "✕", "□"];
export const FACE_LABELS = ["triangle", "circle", "cross", "square"];

export function faceFromEvent(event: KeyboardEvent): number | null {
  const value = FACE_KEYS[event.code];
  return value === undefined ? null : value;
}
```

- [ ] **Step 4: Write `web/src/games/SimonSays.tsx`**

```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { FACE_GLYPHS, FACE_LABELS, faceFromEvent } from "../lib/input";
import type { GameProps } from "./types";

/** Mirrors server/xxvi/games/seeds.py — counter-mode SHA-256, byte % 4.
 *  Any change here must be made there too, and the pinned vector test
 *  in web/tests/seq.test.ts is what catches it if it isn't. */
export async function simonSequence(seed: string, length: number): Promise<number[]> {
  const out: number[] = [];
  let counter = 0;
  while (out.length < length) {
    const data = new TextEncoder().encode(`${seed}:${counter}`);
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", data));
    for (const byte of digest) out.push(byte % 4);
    counter += 1;
  }
  return out.slice(0, length);
}

export function SimonSays({ seed, params, onFinish }: GameProps) {
  const length = Math.trunc(params.length ?? 4);
  const [sequence, setSequence] = useState<number[]>([]);
  const [showing, setShowing] = useState<number | null>(null);
  const [phase, setPhase] = useState<"watch" | "repeat">("watch");
  const entered = useRef<number[]>([]);
  const started = useRef(Date.now());

  useEffect(() => {
    void simonSequence(seed, length).then(setSequence);
  }, [seed, length]);

  useEffect(() => {
    if (!sequence.length || phase !== "watch") return;
    let index = 0;
    const step = setInterval(() => {
      if (index >= sequence.length) {
        clearInterval(step);
        setShowing(null);
        setPhase("repeat");
        started.current = Date.now();
        return;
      }
      setShowing(sequence[index]);
      index += 1;
      setTimeout(() => setShowing(null), 380);
    }, 620);
    return () => clearInterval(step);
  }, [sequence, phase]);

  const press = useCallback(
    (face: number) => {
      if (phase !== "repeat") return;
      entered.current = [...entered.current, face];
      const position = entered.current.length - 1;

      if (entered.current[position] !== sequence[position]) {
        onFinish({
          passed: false,
          durationMs: Date.now() - started.current,
          inputCount: entered.current.length,
          score: position,
          sequence: entered.current,
        });
        return;
      }
      if (entered.current.length === sequence.length) {
        onFinish({
          passed: true,
          durationMs: Date.now() - started.current,
          inputCount: entered.current.length,
          score: sequence.length,
          sequence: entered.current,
        });
      }
    },
    [phase, sequence, onFinish],
  );

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const face = faceFromEvent(event);
      if (face !== null) { event.preventDefault(); press(face); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [press]);

  return (
    <section className="game game--simon">
      <p className="game__prompt">{phase === "watch" ? "watch" : "repeat"}</p>
      <div className="game__faces">
        {FACE_GLYPHS.map((glyph, face) => (
          <button
            key={face}
            className={`face face--${face} ${showing === face ? "is-lit" : ""}`}
            aria-label={FACE_LABELS[face]}
            onClick={() => press(face)}
            disabled={phase !== "repeat"}
          >
            {glyph}
          </button>
        ))}
      </div>
      <p className="game__progress">
        {entered.current.length} / {sequence.length}
      </p>
    </section>
  );
}
```

- [ ] **Step 5: Write `web/src/games/registry.ts` and `web/src/games/GameHost.tsx`**

```ts
// web/src/games/registry.ts
import type { ComponentType } from "react";
import { SimonSays } from "./SimonSays";
import type { GameProps } from "./types";

export const GAMES: Record<string, ComponentType<GameProps>> = {
  simon: SimonSays,
  // update, drift, trophy_run land in Tasks 19–20
};
```

```tsx
// web/src/games/GameHost.tsx
import { GAMES } from "./registry";
import { api, type SegmentBrief } from "../lib/client";
import type { GameOutcome } from "./types";

export function GameHost({ brief, onDone }: { brief: SegmentBrief; onDone: () => void }) {
  const Game = GAMES[brief.mechanic];
  if (!Game) return <p role="alert">unknown mechanic: {brief.mechanic}</p>;

  const finish = async (outcome: GameOutcome) => {
    // The server decides pass or fail. `passed_client_side` is advisory.
    await api.submitGame(brief.token, {
      mechanic: brief.mechanic,
      passed_client_side: outcome.passed,
      duration_ms: outcome.durationMs,
      input_count: outcome.inputCount,
      score: outcome.score,
      sequence: outcome.sequence,
    });
    onDone();
  };

  return <Game seed={brief.seed} params={brief.params} onFinish={finish} />;
}
```

- [ ] **Step 6: Write the Simon component test**

```tsx
// web/tests/simon.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SimonSays, simonSequence } from "../src/games/SimonSays";
import { FACE_LABELS } from "../src/lib/input";

describe("SimonSays", () => {
  it("passes when the full sequence is entered correctly", async () => {
    const onFinish = vi.fn();
    render(<SimonSays seed="s" params={{ length: 3 }} onFinish={onFinish} />);
    const expected = await simonSequence("s", 3);

    await waitFor(() => expect(screen.getByText("repeat")).toBeDefined(), { timeout: 5000 });
    for (const face of expected) {
      await userEvent.click(screen.getByLabelText(FACE_LABELS[face]));
    }
    expect(onFinish).toHaveBeenCalledWith(expect.objectContaining({ passed: true, score: 3 }));
  });

  it("fails immediately on the first wrong press", async () => {
    const onFinish = vi.fn();
    render(<SimonSays seed="s" params={{ length: 3 }} onFinish={onFinish} />);
    const expected = await simonSequence("s", 3);

    await waitFor(() => expect(screen.getByText("repeat")).toBeDefined(), { timeout: 5000 });
    const wrong = (expected[0] + 1) % 4;
    await userEvent.click(screen.getByLabelText(FACE_LABELS[wrong]));

    expect(onFinish).toHaveBeenCalledWith(expect.objectContaining({ passed: false }));
  });
});
```

- [ ] **Step 7: Pin the cross-language vector**

Run: `cd server && python -c "from xxvi.games.seeds import simon_sequence; print(simon_sequence('pinned', 8))"`
Paste the output into `SERVER_VECTOR` in `web/tests/seq.test.ts`.

- [ ] **Step 8: Run the tests and confirm they pass**

Run: `cd web && npm test`
Expected: PASS, including the pinned cross-language vector

- [ ] **Step 9: Commit**

```bash
git add web
git commit -m "feat: add game harness and Simon Says with cross-language seed parity"
```

---

## Task 19: System Update and Stick Drift

**Files:**
- Create: `web/src/games/SystemUpdate.tsx`, `web/src/games/StickDrift.tsx`
- Modify: `web/src/games/registry.ts`
- Test: `web/tests/games.test.tsx`

**Interfaces:**
- Consumes: `GameProps`, `GameOutcome` (Task 18)
- Produces: `SystemUpdate` (reads `params.taps_required`), `StickDrift` (reads `params.duration_ms`, `params.drift_rate`); both registered in `GAMES`.

- [ ] **Step 1: Write the failing tests**

```tsx
// web/tests/games.test.tsx
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { StickDrift } from "../src/games/StickDrift";
import { SystemUpdate } from "../src/games/SystemUpdate";

describe("SystemUpdate", () => {
  it("finishes once the required taps land", async () => {
    const onFinish = vi.fn();
    render(<SystemUpdate seed="s" params={{ taps_required: 3 }} onFinish={onFinish} />);
    const button = screen.getByRole("button", { name: /install/i });
    for (let i = 0; i < 3; i += 1) await userEvent.click(button);
    expect(onFinish).toHaveBeenCalledWith(
      expect.objectContaining({ passed: true, inputCount: 3 }),
    );
  });

  it("drops the bar back to 1% partway through, at least once", async () => {
    render(<SystemUpdate seed="s" params={{ taps_required: 10 }} onFinish={vi.fn()} />);
    const button = screen.getByRole("button", { name: /install/i });
    const seen: number[] = [];
    for (let i = 0; i < 9; i += 1) {
      await userEvent.click(button);
      seen.push(Number(screen.getByLabelText("progress").textContent!.replace("%", "")));
    }
    expect(Math.min(...seen.slice(1))).toBeLessThan(Math.max(...seen));
  });
});

describe("StickDrift", () => {
  it("passes when the reticle is held on target for the full duration", () => {
    vi.useFakeTimers();
    const onFinish = vi.fn();
    render(<StickDrift seed="s" params={{ duration_ms: 1000, drift_rate: 0 }} onFinish={onFinish} />);
    act(() => { vi.advanceTimersByTime(1200); });
    expect(onFinish).toHaveBeenCalledWith(expect.objectContaining({ passed: true }));
    vi.useRealTimers();
  });

  it("fails when the reticle leaves the target zone", () => {
    vi.useFakeTimers();
    const onFinish = vi.fn();
    render(<StickDrift seed="s" params={{ duration_ms: 5000, drift_rate: 40 }} onFinish={onFinish} />);
    act(() => { vi.advanceTimersByTime(2000); });
    expect(onFinish).toHaveBeenCalledWith(expect.objectContaining({ passed: false }));
    vi.useRealTimers();
  });
});
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd web && npm test games`
Expected: FAIL — cannot resolve the two game modules

- [ ] **Step 3: Write `web/src/games/SystemUpdate.tsx`**

```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import type { GameProps } from "./types";

const SETBACKS = [0.45, 0.8]; // fractions of the way through where it drops

export function SystemUpdate({ params, onFinish }: GameProps) {
  const required = Math.trunc(params.taps_required ?? 20);
  const [taps, setTaps] = useState(0);
  const [floor, setFloor] = useState(0);
  const fired = useRef<Set<number>>(new Set());
  const started = useRef(Date.now());

  const percent = Math.min(99, Math.round(((taps - floor) / (required - floor || 1)) * 99));

  const tap = useCallback(() => {
    const next = taps + 1;
    const fraction = next / required;

    for (const [index, mark] of SETBACKS.entries()) {
      if (fraction >= mark && !fired.current.has(index)) {
        fired.current.add(index);
        setFloor(next);           // the bar snaps back to 1%
        setTaps(next);
        return;
      }
    }

    setTaps(next);
    if (next >= required) {
      onFinish({
        passed: true,
        durationMs: Date.now() - started.current,
        inputCount: next,
        score: next,
        sequence: [],
      });
    }
  }, [taps, required, onFinish]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.code === "Space" || event.code === "Enter") { event.preventDefault(); tap(); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [tap]);

  return (
    <section className="game game--update">
      <h2>system update 1 of 47</h2>
      <div className="update__bar"><div className="update__fill" style={{ width: `${percent}%` }} /></div>
      <p aria-label="progress" className="update__percent">{percent}%</p>
      <button onClick={tap} autoFocus>install (space)</button>
    </section>
  );
}
```

- [ ] **Step 4: Write `web/src/games/StickDrift.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";
import type { GameProps } from "./types";

const TICK_MS = 50;
const LIMIT = 100; // how far the reticle may stray before the run fails

export function StickDrift({ params, onFinish }: GameProps) {
  const duration = Math.trunc(params.duration_ms ?? 20000);
  const driftRate = params.drift_rate ?? 1;
  const [offset, setOffset] = useState(0);
  const offsetRef = useRef(0);
  const inputs = useRef(0);
  const elapsed = useRef(0);
  const done = useRef(false);
  const started = useRef(Date.now());

  useEffect(() => {
    const finish = (passed: boolean) => {
      if (done.current) return;
      done.current = true;
      onFinish({
        passed,
        durationMs: Date.now() - started.current,
        inputCount: inputs.current,
        score: elapsed.current,
        sequence: [],
      });
    };

    const timer = setInterval(() => {
      elapsed.current += TICK_MS;
      offsetRef.current += driftRate;      // the stick always pulls one way
      setOffset(offsetRef.current);

      if (Math.abs(offsetRef.current) > LIMIT) finish(false);
      else if (elapsed.current >= duration) finish(true);
    }, TICK_MS);

    const handler = (event: KeyboardEvent) => {
      const nudge = event.code === "ArrowLeft" ? -6 : event.code === "ArrowRight" ? 6 : 0;
      if (!nudge) return;
      event.preventDefault();
      inputs.current += 1;
      offsetRef.current += nudge;
      setOffset(offsetRef.current);
    };

    window.addEventListener("keydown", handler);
    return () => { clearInterval(timer); window.removeEventListener("keydown", handler); };
  }, [duration, driftRate, onFinish]);

  return (
    <section className="game game--drift">
      <h2>hold it steady</h2>
      <div className="drift__track">
        <div className="drift__target" />
        <div className="drift__reticle" style={{ transform: `translateX(${offset}px)` }} aria-label="reticle" />
      </div>
      <p className="drift__hint">← → to correct</p>
    </section>
  );
}
```

- [ ] **Step 5: Register both mechanics**

```ts
// web/src/games/registry.ts
import { SimonSays } from "./SimonSays";
import { StickDrift } from "./StickDrift";
import { SystemUpdate } from "./SystemUpdate";

export const GAMES: Record<string, ComponentType<GameProps>> = {
  simon: SimonSays,
  update: SystemUpdate,
  drift: StickDrift,
};
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `cd web && npm test`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add web
git commit -m "feat: add System Update and Stick Drift mechanics"
```

---

## Task 20: Trophy Run, questions, checkpoints, and the code reveal

Completing this task completes the never-cross line end to end.

**Files:**
- Create: `web/src/games/TrophyRun.tsx`, `web/src/shell/Question.tsx`, `web/src/shell/Checkpoint.tsx`, `web/src/shell/CodeReveal.tsx`
- Modify: `web/src/games/registry.ts`, `web/src/Console.tsx`
- Test: `web/tests/trophyrun.test.tsx`, `web/tests/question.test.tsx`, `web/tests/checkpoint.test.tsx`

**Interfaces:**
- Consumes: `GameProps` (Task 18); `api.submitAnswer`, `api.submitCheckpoint` (Task 14)
- Produces: `TrophyRun` (reads `params.prompts`, `params.window_ms`), `<Question question onAnswered />`, `<Checkpoint onPassed />`, `<CodeReveal release />`.

- [ ] **Step 1: Write the failing tests**

```tsx
// web/tests/trophyrun.test.tsx
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TrophyRun } from "../src/games/TrophyRun";

describe("TrophyRun", () => {
  it("fails when a prompt's window expires without input", () => {
    vi.useFakeTimers();
    const onFinish = vi.fn();
    render(<TrophyRun seed="s" params={{ prompts: 4, window_ms: 500 }} onFinish={onFinish} />);
    act(() => { vi.advanceTimersByTime(700); });
    expect(onFinish).toHaveBeenCalledWith(expect.objectContaining({ passed: false }));
    vi.useRealTimers();
  });

  it("shows one prompt at a time", () => {
    vi.useFakeTimers();
    render(<TrophyRun seed="s" params={{ prompts: 4, window_ms: 5000 }} onFinish={vi.fn()} />);
    expect(screen.getAllByLabelText(/prompt/i)).toHaveLength(1);
    vi.useRealTimers();
  });
});
```

```tsx
// web/tests/question.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Question } from "../src/shell/Question";

const question = { prompt: "what did I say?", choices: ["a", "b", "c", "d"] };

describe("Question", () => {
  it("renders every choice and no answer key", () => {
    const { container } = render(<Question question={question} onAnswered={vi.fn()} />);
    expect(screen.getAllByRole("button")).toHaveLength(4);
    expect(container.innerHTML).not.toContain("answer");
  });

  it("reports the chosen index", async () => {
    const onAnswered = vi.fn();
    render(<Question question={question} onAnswered={onAnswered} />);
    await userEvent.click(screen.getByRole("button", { name: "c" }));
    expect(onAnswered).toHaveBeenCalledWith(2);
  });

  it("disables every choice after one is picked, so a double-click cannot double-submit", async () => {
    render(<Question question={question} onAnswered={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "a" }));
    for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
  });
});
```

```tsx
// web/tests/checkpoint.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Checkpoint } from "../src/shell/Checkpoint";
import { api } from "../src/lib/client";

vi.mock("../src/lib/client", () => ({ api: { submitCheckpoint: vi.fn() } }));

describe("Checkpoint", () => {
  beforeEach(() => vi.mocked(api.submitCheckpoint).mockReset());

  it("shows attempts remaining after a wrong code", async () => {
    vi.mocked(api.submitCheckpoint).mockResolvedValue({
      outcome: "wrong", attempts_remaining: 2, released: null, run: {} as never,
    });
    render(<Checkpoint onPassed={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("code"), "NOPE");
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(await screen.findByText(/2/)).toBeDefined();
  });

  it("tells him to call Kritish once locked, rather than dead-ending", async () => {
    vi.mocked(api.submitCheckpoint).mockResolvedValue({
      outcome: "locked", attempts_remaining: 0, released: null, run: {} as never,
    });
    render(<Checkpoint onPassed={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("code"), "NOPE");
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/kritish/i);
  });

  it("hands the release up when the code is right", async () => {
    const release = { reward_id: 1, label: "₹1,000", code: "ABC-123" };
    vi.mocked(api.submitCheckpoint).mockResolvedValue({
      outcome: "ok", attempts_remaining: null, released: release, run: {} as never,
    });
    const onPassed = vi.fn();
    render(<Checkpoint onPassed={onPassed} />);
    await userEvent.type(screen.getByLabelText("code"), "RIGHT");
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(onPassed).toHaveBeenCalledWith(release);
  });
});
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd web && npm test`
Expected: FAIL — the three new modules do not resolve

- [ ] **Step 3: Write `web/src/games/TrophyRun.tsx`**

```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { FACE_GLYPHS, FACE_LABELS, faceFromEvent } from "../lib/input";
import { simonSequence } from "./SimonSays";
import type { GameProps } from "./types";

export function TrophyRun({ seed, params, onFinish }: GameProps) {
  const total = Math.trunc(params.prompts ?? 6);
  const windowMs = Math.trunc(params.window_ms ?? 1200);
  const [prompts, setPrompts] = useState<number[]>([]);
  const [index, setIndex] = useState(0);
  const hits = useRef(0);
  const inputs = useRef(0);
  const done = useRef(false);
  const started = useRef(Date.now());

  useEffect(() => { void simonSequence(seed, total).then(setPrompts); }, [seed, total]);

  const finish = useCallback((passed: boolean) => {
    if (done.current) return;
    done.current = true;
    onFinish({
      passed,
      durationMs: Date.now() - started.current,
      inputCount: inputs.current,
      score: hits.current,
      sequence: [],
    });
  }, [onFinish]);

  useEffect(() => {
    if (!prompts.length || done.current) return;
    if (index >= prompts.length) { finish(hits.current >= total); return; }
    const timer = setTimeout(() => finish(false), windowMs);   // miss the window, run over
    return () => clearTimeout(timer);
  }, [prompts, index, windowMs, total, finish]);

  const press = useCallback((face: number) => {
    if (done.current || index >= prompts.length) return;
    inputs.current += 1;
    if (face !== prompts[index]) { finish(false); return; }
    hits.current += 1;
    setIndex((n) => n + 1);
  }, [index, prompts, finish]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const face = faceFromEvent(event);
      if (face !== null) { event.preventDefault(); press(face); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [press]);

  const current = prompts[index];

  return (
    <section className="game game--trophyrun">
      <h2>trophy run</h2>
      {current !== undefined && (
        <button
          className={`prompt prompt--${current}`}
          aria-label={`prompt ${FACE_LABELS[current]}`}
          onClick={() => press(current)}
        >
          {FACE_GLYPHS[current]}
        </button>
      )}
      <p className="game__progress">{hits.current} / {total}</p>
    </section>
  );
}
```

Register it: add `trophy_run: TrophyRun` to `GAMES` in `web/src/games/registry.ts`.

- [ ] **Step 4: Write `web/src/shell/Question.tsx`**

```tsx
import { useState } from "react";
import type { QuestionView } from "../lib/client";

type Props = { question: QuestionView; onAnswered: (choice: number) => void };

export function Question({ question, onAnswered }: Props) {
  const [locked, setLocked] = useState(false);

  const choose = (index: number) => {
    if (locked) return;
    setLocked(true);
    onAnswered(index);
  };

  return (
    <section className="question">
      <h2 className="question__prompt">{question.prompt}</h2>
      <ul className="question__choices">
        {question.choices.map((choice, index) => (
          <li key={index}>
            <button onClick={() => choose(index)} disabled={locked}>
              {choice}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 5: Write `web/src/shell/Checkpoint.tsx` and `web/src/shell/CodeReveal.tsx`**

```tsx
import { useState } from "react";
import { api, type CheckpointResponse } from "../lib/client";

type Release = NonNullable<CheckpointResponse["released"]>;

export function Checkpoint({ onPassed }: { onPassed: (release: Release | null) => void }) {
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<CheckpointResponse | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    const response = await api.submitCheckpoint(code.trim().toUpperCase());
    setStatus(response);
    setBusy(false);
    if (response.outcome === "ok") onPassed(response.released);
  };

  return (
    <section className="checkpoint">
      <h2>checkpoint</h2>
      <p>kritish has the code.</p>
      <form onSubmit={submit}>
        <input aria-label="code" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} autoFocus />
        <button type="submit" disabled={busy || status?.outcome === "locked"}>submit</button>
      </form>

      {status?.outcome === "wrong" && (
        <p role="status">wrong. {status.attempts_remaining} attempts left.</p>
      )}
      {/* A lockout must never read as a dead end — he is on a call with the
          one person who can clear it. */}
      {status?.outcome === "locked" && (
        <p role="alert">locked. tell kritish — he can clear it from his end.</p>
      )}
    </section>
  );
}
```

```tsx
// web/src/shell/CodeReveal.tsx
import { useState } from "react";

type Props = { release: { reward_id: number; label: string; code: string } };

export function CodeReveal({ release }: Props) {
  const [copied, setCopied] = useState(false);

  return (
    <section className="reveal">
      <p className="reveal__label">{release.label}</p>
      <p className="reveal__code" aria-label="redemption code">{release.code}</p>
      <button
        onClick={async () => {
          await navigator.clipboard?.writeText(release.code).catch(() => undefined);
          setCopied(true);
        }}
      >
        {copied ? "copied" : "copy"}
      </button>
      <p className="reveal__note">screenshot this. it is also in your email.</p>
    </section>
  );
}
```

- [ ] **Step 6: Wire the remaining phases into `Console.tsx`**

Replace the `default:` branch with:

```tsx
    case "game": return <SegmentGame onDone={refresh} />;
    case "question":
      return run.question ? (
        <Question
          question={run.question}
          onAnswered={async (choice) => { await api.submitAnswer(choice); await refresh(); }}
        />
      ) : null;
    case "checkpoint":
      return <Checkpoint onPassed={async (release) => { setRelease(release); await refresh(); }} />;
    case "complete":
      return (
        <TrophyCabinet
          trophies={content.trophies}
          earned={run.trophies}
          closing={content.copy.closing}
        />
      );
    default: return null;
```

`content` comes from `GET /api/content` (Task 11b). Add to `Console.tsx`:

```tsx
const [content, setContent] = useState<ContentView | null>(null);
useEffect(() => { void fetch("/api/content", { credentials: "same-origin" })
  .then((r) => r.json()).then(setContent); }, [run.trophies.length]);
```

Re-fetching when the trophy count changes is what un-masks a hidden trophy's name after it pops, since the masking happens server-side.

Add the matching type to `web/src/lib/client.ts`:

```ts
export type TrophyView = { id: string; name: string; grade: string; hidden: boolean };
export type ContentView = {
  copy: { coming_soon: string; teaser: string; how_to_play: string; closing: string };
  trophies: TrophyView[];
};
```

Also add a `SegmentGame` helper in the same file that calls `api.startSegment()` once on mount and renders `<GameHost brief onDone />`, plus `const [release, setRelease] = useState<Release | null>(null)` rendered as `<CodeReveal release={release} />` above the current screen whenever it is set.

- [ ] **Step 7: Run the whole frontend suite**

Run: `cd web && npm test && npm run build`
Expected: PASS, and a clean production build

- [ ] **Step 8: Commit**

```bash
git add web
git commit -m "feat: add trophy run, questions, checkpoints and code reveal"
```

---

## Task 21: Operator dashboard

**Files:**
- Create: `web/src/Operator.tsx`, `web/src/operator.css`
- Modify: `web/src/App.tsx`
- Test: `web/tests/operator.test.tsx`

**Interfaces:**
- Consumes: `connect` (Task 14); operator endpoints (Task 13)
- Produces: `<Operator />` with live run state and buttons for approve, toast, unlock-gate and force-golive.

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/operator.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Operator } from "../src/Operator";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);
vi.stubGlobal("WebSocket", class { close() {} } as never);

const state = {
  live_forced: false,
  runs: [{ id: 1, difficulty: "devil", phase: "checkpoint", segment: 4,
           cleared_segments: [1, 2, 3, 4], released_rewards: [] }],
};

describe("Operator", () => {
  it("shows the live run and its phase", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => state });
    render(<Operator />);
    expect(await screen.findByText(/checkpoint/)).toBeDefined();
    expect(screen.getByText(/devil/)).toBeDefined();
  });

  it("requires a confirmation before releasing a code", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => state });
    render(<Operator />);
    await userEvent.click(await screen.findByRole("button", { name: /release ₹|release reward 1/i }));
    // Nothing is posted until the confirm step is taken.
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/approve"))).toBe(false),
    );
    await userEvent.click(screen.getByRole("button", { name: /confirm/i }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/approve"))).toBe(true),
    );
  });
});
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd web && npm test operator`
Expected: FAIL — cannot resolve `../src/Operator`

- [ ] **Step 3: Write `web/src/Operator.tsx`**

```tsx
import { useCallback, useEffect, useState } from "react";
import { connect } from "./lib/ws";

type RunSummary = {
  id: number; difficulty: string | null; phase: string; segment: number;
  cleared_segments: number[]; released_rewards: number[];
};
type OperatorState = { live_forced: boolean; runs: RunSummary[] };

const post = (path: string, body?: unknown) =>
  fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });

export function Operator() {
  const [state, setState] = useState<OperatorState | null>(null);
  const [pending, setPending] = useState<{ runId: number; rewardId: number } | null>(null);
  const [toast, setToast] = useState("");
  const [lastCode, setLastCode] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const response = await fetch("/api/operator/state", { credentials: "same-origin" });
    setState(await response.json());
  }, []);

  useEffect(() => {
    void refresh();
    const socket = connect("/api/ws/operator", { run_state: () => void refresh() });
    const poll = setInterval(refresh, 3000);
    return () => { socket.close(); clearInterval(poll); };
  }, [refresh]);

  if (!state) return null;

  const approve = async () => {
    if (!pending) return;
    const response = await post("/api/operator/approve", {
      run_id: pending.runId, reward_id: pending.rewardId,
    });
    const body = await response.json().catch(() => null);
    setLastCode(body?.code ?? "already released");
    setPending(null);
    await refresh();
  };

  return (
    <main className="operator">
      <header>
        <h1>operator</h1>
        <button onClick={async () => { await post("/api/operator/force-golive"); await refresh(); }}>
          {state.live_forced ? "forced live" : "force go-live"}
        </button>
      </header>

      {state.runs.map((run) => (
        <section key={run.id} className="operator__run">
          <h2>run {run.id}</h2>
          <dl>
            <dt>difficulty</dt><dd>{run.difficulty ?? "—"}</dd>
            <dt>phase</dt><dd>{run.phase}</dd>
            <dt>segment</dt><dd>{run.segment} / 8</dd>
            <dt>cleared</dt><dd>{run.cleared_segments.join(", ") || "none"}</dd>
            <dt>released</dt><dd>{run.released_rewards.join(", ") || "none"}</dd>
          </dl>

          <div className="operator__actions">
            {[1, 2].map((rewardId) => (
              <button
                key={rewardId}
                disabled={run.released_rewards.includes(rewardId)}
                onClick={() => setPending({ runId: run.id, rewardId })}
              >
                release reward {rewardId}
              </button>
            ))}
            {(["checkpoint_1", "checkpoint_2", "activation"] as const).map((gate) => (
              <button key={gate} onClick={() => post("/api/operator/unlock-gate", { run_id: run.id, gate })}>
                clear {gate}
              </button>
            ))}
          </div>

          <form
            onSubmit={async (event) => {
              event.preventDefault();
              await post("/api/operator/toast", { run_id: run.id, text: toast });
              setToast("");
            }}
          >
            <input value={toast} onChange={(e) => setToast(e.target.value)} placeholder="say something" />
            <button type="submit">send</button>
          </form>
        </section>
      ))}

      {/* Releasing real money is a two-step action, deliberately. */}
      {pending && (
        <div role="dialog" className="operator__confirm">
          <p>release reward {pending.rewardId} for run {pending.runId}?</p>
          <button onClick={approve}>confirm</button>
          <button onClick={() => setPending(null)}>cancel</button>
        </div>
      )}

      {lastCode && <p className="operator__code">released: {lastCode}</p>}
    </main>
  );
}
```

- [ ] **Step 4: Route to it from `App.tsx`**

Replace the operator placeholder with `return <Operator />;`.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd web && npm test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web
git commit -m "feat: add operator dashboard with two-step code release"
```

---

## Task 22: Deployment — Docker Compose, Caddy, and the dress rehearsal

**Files:**
- Create: `docker-compose.yml`, `Caddyfile`, `server/Dockerfile`, `web/Dockerfile`
- Create: `docs/runbook.md`
- Modify: `.gitignore` (confirm `.env` and `config/run.yaml` are excluded)

**Interfaces:**
- Consumes: everything
- Produces: `docker compose up -d` serving the app over TLS with a working `/api/health`.

- [ ] **Step 1: Write `server/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY xxvi ./xxvi
COPY alembic ./alembic
COPY alembic.ini ./
EXPOSE 8000
CMD ["uvicorn", "xxvi.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write `web/Dockerfile`**

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
```

- [ ] **Step 3: Write `docker-compose.yml`**

Neon is managed and sits outside compose. Only the app and the proxy run here.

```yaml
services:
  api:
    build: ./server
    env_file: .env
    volumes:
      - ./config:/app/config:ro     # run.yaml is mounted, never baked into the image
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')"]
      interval: 30s
      timeout: 5s
      retries: 3

  caddy:
    build: ./web
    depends_on:
      - api
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
    restart: unless-stopped

volumes:
  caddy_data:
```

- [ ] **Step 4: Write `Caddyfile`**

```
{$SITE_DOMAIN} {
	encode gzip

	# WebSockets and the API go to FastAPI; everything else is the SPA.
	handle /api/* {
		reverse_proxy api:8000
	}

	handle {
		root * /srv
		try_files {path} /index.html
		file_server
	}
}
```

- [ ] **Step 5: Confirm nothing secret is tracked**

Run: `git status --short && git ls-files | grep -E '(^\.env$|config/run\.yaml)' || echo "clean: no secrets tracked"`
Expected: `clean: no secrets tracked`

- [ ] **Step 6: Bring it up and verify**

```bash
docker compose up -d --build
curl -sf https://$SITE_DOMAIN/api/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 7: Write `docs/runbook.md`**

```markdown
# XXVI — night-of runbook

## Non-negotiable
The codes are in my notes. If anything breaks, paste them into WhatsApp.
The gift is guaranteed; the experience is what's allowed to fail.

## Several days before — dress rehearsal
Run the whole thing on the actual laptop, in fullscreen, screen-sharing to
Discord, with dummy codes. Not optional. Verify:

- [ ] Full run start to finish, both difficulties
- [ ] **Discord: share the ENTIRE SCREEN, not the browser window.**
      Fullscreen can black out a window capture, badly on macOS.
- [ ] Trophy pops are legible through Discord compression
- [ ] Trophy pops read as complete with the sound muted
- [ ] Operator dashboard updates live while he plays
- [ ] Toast lands on his screen mid-game
- [ ] Force go-live works
- [ ] Clear-lockout works after three wrong checkpoint codes
- [ ] `python -m xxvi.cli release --run N --reward 1` works with the dashboard closed

## On the 20th, before midnight IST
- [ ] Put the REAL codes in `.env`, `docker compose up -d`
- [ ] Confirm `/api/health`
- [ ] Confirm `/api/session` reports `live: false` with a sane countdown
- [ ] Reset his run: `DELETE FROM runs WHERE account_id = <his>;` (cascade events/trophies)
- [ ] Send the riddle email carrying ACTIVATION_CODE
- [ ] Open the operator dashboard and confirm his profile flips to online

## If it goes wrong
| Symptom | Do this |
|---|---|
| Gate didn't open at midnight | Force go-live on the dashboard |
| He's locked out of a checkpoint | Clear the gate on the dashboard |
| Dashboard is broken | `python -m xxvi.cli release --run N --reward M` |
| Server is down | WhatsApp the codes. Laugh about it. |
```

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml Caddyfile server/Dockerfile web/Dockerfile docs/runbook.md
git commit -m "feat: add Docker Compose deployment, Caddy TLS and night-of runbook"
```

---

## Task 23 (cuttable): Gamepad support

First to cut. Keyboard remains the supported path throughout.

**Files:**
- Create: `web/src/lib/gamepad.ts`
- Modify: `web/src/games/SimonSays.tsx`, `web/src/games/TrophyRun.tsx`, `web/src/games/StickDrift.tsx`
- Test: `web/tests/gamepad.test.ts`

**Interfaces:**
- Consumes: nothing
- Produces: `useGamepadFace(onFace: (face: number) => void): boolean` (returns whether a pad is connected), `DUALSENSE_FACE_MAP`.

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/gamepad.test.ts
import { describe, expect, it } from "vitest";
import { faceFromButtons, DUALSENSE_FACE_MAP } from "../src/lib/gamepad";

describe("faceFromButtons", () => {
  it("maps the standard gamepad face buttons to our indices", () => {
    // Standard mapping: 0 cross, 1 circle, 2 square, 3 triangle.
    expect(faceFromButtons([{ pressed: true }, {}, {}, {}] as never)).toBe(DUALSENSE_FACE_MAP[0]);
    expect(faceFromButtons([{}, {}, {}, { pressed: true }] as never)).toBe(DUALSENSE_FACE_MAP[3]);
  });

  it("returns null when nothing is pressed", () => {
    expect(faceFromButtons([{}, {}, {}, {}] as never)).toBeNull();
  });
});
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd web && npm test gamepad`
Expected: FAIL — cannot resolve `../src/lib/gamepad`

- [ ] **Step 3: Write `web/src/lib/gamepad.ts`**

```ts
import { useEffect, useState } from "react";

/** Standard gamepad button order is cross, circle, square, triangle.
 *  Our face indices are triangle 0, circle 1, cross 2, square 3. */
export const DUALSENSE_FACE_MAP = [2, 1, 3, 0];

export function faceFromButtons(buttons: readonly GamepadButton[]): number | null {
  for (let index = 0; index < 4; index += 1) {
    if (buttons[index]?.pressed) return DUALSENSE_FACE_MAP[index];
  }
  return null;
}

/** Enhancement only. A pad that never enumerates changes nothing. */
export function useGamepadFace(onFace: (face: number) => void): boolean {
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (typeof navigator === "undefined" || !navigator.getGamepads) return;
    let frame = 0;
    let previous: number | null = null;

    const poll = () => {
      const pad = navigator.getGamepads?.()[0];
      setConnected(Boolean(pad));
      if (pad) {
        const face = faceFromButtons(pad.buttons);
        if (face !== null && face !== previous) onFace(face);
        previous = face;
      }
      frame = requestAnimationFrame(poll);
    };

    frame = requestAnimationFrame(poll);
    return () => cancelAnimationFrame(frame);
  }, [onFace]);

  return connected;
}
```

- [ ] **Step 4: Wire it into the face-button games**

In `SimonSays.tsx` and `TrophyRun.tsx`, add alongside the existing keyboard listener:

```tsx
const padConnected = useGamepadFace(press);
```

and render `{padConnected && <p className="game__hint">controller detected</p>}`. The keyboard handler stays exactly as it is.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd web && npm test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web
git commit -m "feat: add optional gamepad input alongside keyboard"
```

---

## Task 24 (cuttable): Hidden trophies

**Files:**
- Modify: `server/xxvi/api/run_service.py`, `server/xxvi/api/run_routes.py`
- Test: `server/tests/test_hidden_trophies.py`

**Interfaces:**
- Consumes: `RunRepository`, `RunService` (Task 12)
- Produces: `HIDDEN_RAGE_QUIT = "hidden-rage-quit"`, `HIDDEN_DRIFT_DENIER = "hidden-drift-denier"`, `HIDDEN_SPEEDRUN = "hidden-speedrun"`; `RunService.check_hidden(run, state) -> list[Trophy]`.

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/test_hidden_trophies.py
import pytest

from xxvi.core.models import Difficulty
from xxvi.persistence.repositories import RunRepository


@pytest.fixture
async def run(sessionmaker, account):
    return await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)


async def test_rage_quit_pops_on_returning_after_a_disconnect(sessionmaker, run, service):
    repo = RunRepository(sessionmaker)
    await repo.append_event(run.id, "player_disconnected", {})
    awarded = await service.check_hidden(run, reconnecting=True)
    assert any(t.id == "hidden-rage-quit" for t in awarded)


async def test_drift_denier_pops_after_three_drift_failures(sessionmaker, run, service):
    repo = RunRepository(sessionmaker)
    for _ in range(3):
        await repo.append_event(run.id, "game_failed", {"mechanic": "drift"})
    awarded = await service.check_hidden(run, reconnecting=False)
    assert any(t.id == "hidden-drift-denier" for t in awarded)


async def test_hidden_trophies_survive_a_devil_wipe(sessionmaker, run):
    repo = RunRepository(sessionmaker)
    await repo.award_trophy(run.id, "hidden-rage-quit")
    await repo.award_trophy(run.id, "game-1")
    await repo.clear_segment_trophies(run.id)
    assert await repo.earned_trophies(run.id) == frozenset({"hidden-rage-quit"})


async def test_hidden_trophies_do_not_gate_the_platinum():
    from xxvi.core.models import Shape
    from xxvi.core.trophies import platinum_earned, required_for_platinum

    shape = Shape()
    assert platinum_earned(required_for_platinum(shape), shape)
```

Add a `service` fixture constructing `RunService` exactly as `build_service` does in Task 12.

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd server && pytest tests/test_hidden_trophies.py -v`
Expected: FAIL — `RunService` has no attribute `check_hidden`

- [ ] **Step 3: Add `check_hidden` to `RunService`**

```python
HIDDEN_RAGE_QUIT = "hidden-rage-quit"
HIDDEN_DRIFT_DENIER = "hidden-drift-denier"
HIDDEN_SPEEDRUN = "hidden-speedrun"
SPEEDRUN_SECONDS = 600


    async def check_hidden(self, run, *, reconnecting: bool = False) -> list[Trophy]:
        """Hidden trophies never gate the platinum and survive a wipe."""
        awarded: list[Trophy] = []

        async def give(trophy_id: str) -> None:
            if await self._repo.award_trophy(run.id, trophy_id):
                awarded.append(self._trophy(trophy_id))

        if reconnecting and await self._repo.has_event(run.id, "player_disconnected", {}):
            await give(HIDDEN_RAGE_QUIT)

        drift_failures = await self._repo.count_events(
            run.id, "game_failed", {"mechanic": "drift"}
        )
        if drift_failures >= 3:
            await give(HIDDEN_DRIFT_DENIER)

        return awarded
```

Add `count_events` to `RunRepository`, mirroring `has_event` but returning a count.

- [ ] **Step 4: Record the mechanic on game failures**

In `RunService.submit_game`, change the failure branch to append `{"mechanic": slot.mechanic}` to the event payload so `check_hidden` has something to count.

- [ ] **Step 5: Call it from the WS connect handler**

In `ws_routes.player_socket`, after `hub.connect(...)`, award any hidden trophies with `reconnecting=True` and broadcast the pops. Append a `player_disconnected` event in the `finally` block.

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `cd server && pytest tests/test_hidden_trophies.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add server
git commit -m "feat: add hidden trophies that survive wipes and never gate the platinum"
```

---

## Final verification

- [ ] **Backend suite green:** `cd server && pytest -v`
- [ ] **Frontend suite green:** `cd web && npm test`
- [ ] **Production build clean:** `cd web && npm run build`
- [ ] **Types in step:** restart the API, `cd web && npm run codegen`, then `git diff --exit-code web/src/api.ts` — a diff means the frontend was built against a stale schema
- [ ] **No secrets tracked:** `git ls-files | grep -E '(^\.env$|config/run\.yaml)'` returns nothing
- [ ] **Codes absent from logs:** `docker compose logs api | grep -F "$REWARD_1_CODE"` returns nothing
- [ ] **Dress rehearsal complete**, per `docs/runbook.md`, on the real laptop, in fullscreen, screen-sharing to Discord

## Content still required (spec §11)

None of it blocks implementation. All of it blocks the 20th.

- [ ] The eight questions — prompts, choices, correct answers, roast copy
- [ ] The riddle carrying `ACTIVATION_CODE`
- [ ] Names for all 19 standard trophies and the 3 hidden ones
- [ ] The closing message on the trophy cabinet
- [ ] Coming-soon copy and the personalised teaser
- [ ] Original trophy art and sound — recreate the feel, ship none of Sony's assets

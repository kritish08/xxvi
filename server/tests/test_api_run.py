import pytest
from httpx import ASGITransport, AsyncClient

from xxvi.auth.passwords import hash_password
from xxvi.content.loader import load_config
from xxvi.games.seeds import simon_sequence
from xxvi.main import create_app, seed_accounts
from xxvi.settings import Settings, get_settings
from tests.paths import EXAMPLE_CONFIG
from sqlalchemy import select

from xxvi.persistence.models import Run
from xxvi.vault.service import VaultService


async def only_run_id(sessionmaker) -> int:
    """The single run in a test database. Read rather than assumed -- the id
    is a sequence value and is not guaranteed to be 1."""
    async with sessionmaker() as session:
        return (await session.execute(select(Run.id))).scalars().one()

CODE = "ABCD-EFGH-IJKL"

# The example config's "drift" segments require duration_ms >= 20000/25000
# (xxvi/games/verify.py's mechanic-specific check) while `RunService.submit_game`
# now also cross-checks duration_ms against REAL wall-clock elapsed time since
# the token was issued (issued_at, MAX_CLOCK_SLACK_MS=2000ms) -- the fix this
# task is required to wire. An HTTP-level test hitting a drift segment with the
# example config's real 20-25s requirement would need to genuinely sleep that
# long to pass honestly. Rather than either slow the suite down by ~45s or
# weaken the wall-clock check to make tests convenient, these fast overrides
# shrink the *requirement* on drift/update/trophy_run segments for the
# playthrough tests below -- simon (the only mechanic actually exercised in
# most tests, since segment 1 is simon) is untouched.
_FAST_PARAMS = {
    # hold_ms must shrink WITH duration_ms: the real config asks for 11-16s
    # inside the zone, which a 100ms test run can never satisfy.
    "drift": {"duration_ms": 100, "hold_ms": 60},
    "update": {"taps_required": 5},
    "trophy_run": {"prompts": 3},
}


def fast_config():
    config = load_config(EXAMPLE_CONFIG)
    games = [
        g.model_copy(update={"params": {**g.params, **_FAST_PARAMS[g.mechanic]}})
        if g.mechanic in _FAST_PARAMS else g
        for g in config.games
    ]
    return config.model_copy(update={"games": games})


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
    app.state.config = fast_config()
    app.state.auto_approve_releases = True  # operator stand-in for tests
    await seed_accounts(sessionmaker, settings)
    # https, not http -- see test_api_auth.py: the login cookie is Secure
    # and httpx's jar drops it on the next request over plain http.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
        yield c


async def reach_first_game(client, difficulty: str) -> None:
    await client.post("/api/run/activate", json={"code": CODE})
    await client.post("/api/run/profile")
    await client.post("/api/run/difficulty", json={"difficulty": difficulty})
    await client.post("/api/run/installed")
    await client.post("/api/run/howto")


def honest_passing_payload(brief: dict, config) -> dict:
    """A game result that honestly passes verify_result for `brief`'s segment
    -- including the real wall-clock cross-check against the token's own
    issue time, not just the internal duration/input_count consistency
    check. Every value here is deliberately small (see `fast_config`) so the
    real elapsed time between issuing the token and this payload being built
    (milliseconds, in a test) stays comfortably under MAX_CLOCK_SLACK_MS.
    """
    slot = next(g for g in config.games if g.segment == brief["segment"])
    match slot.mechanic:
        case "simon":
            length = int(slot.params.get("length", 4))
            return {
                "mechanic": "simon", "passed_client_side": True,
                "duration_ms": length * 60 + 40, "input_count": length, "score": length,
                "sequence": simon_sequence(brief["seed"], length),
            }
        case "update":
            required = int(slot.params.get("taps_required", 20))
            return {
                "mechanic": "update", "passed_client_side": True,
                "duration_ms": required * 60 + 40, "input_count": required,
                "score": required, "sequence": [],
            }
        case "drift":
            duration = int(slot.params.get("duration_ms", 20000))
            # `score` is milliseconds held inside the target zone, which is
            # now what the drift mechanic actually measures -- a run that
            # merely lasted long enough no longer passes.
            return {
                "mechanic": "drift", "passed_client_side": True,
                "duration_ms": duration + 10, "input_count": 1,
                "score": duration, "sequence": [],
            }
        case "trophy_run":
            prompts = int(slot.params.get("prompts", 6))
            return {
                "mechanic": "trophy_run", "passed_client_side": True,
                "duration_ms": prompts * 60 + 40, "input_count": prompts,
                "score": prompts, "sequence": [],
            }
        case "stack":
            target = int(slot.params.get("target", 8))
            return {
                "mechanic": "stack", "passed_client_side": True,
                "duration_ms": target * 60 + 40, "input_count": target,
                "score": target, "sequence": [],
            }
        case other:  # pragma: no cover - defensive, config is fixed
            raise AssertionError(f"unhandled mechanic {other!r} in test helper")


def failing_payload(mechanic: str) -> dict:
    """A game result guaranteed to fail verify_result regardless of segment:
    input_count=1 with duration_ms below the per-input floor."""
    return {
        "mechanic": mechanic, "passed_client_side": False,
        "duration_ms": 1, "input_count": 1, "score": 0, "sequence": [0],
    }


async def clear_segment(client, config) -> dict:
    brief = (await client.post("/api/run/segment/start")).json()
    result = honest_passing_payload(brief, config)
    await client.post(
        "/api/run/segment/game", json={"token": brief["token"], "result": result}
    )
    question = (await client.get("/api/run")).json()["question"]
    assert question is not None, "a passing game submission must reach the question phase"
    correct_answer = config.questions[brief["segment"] - 1].accept[0]
    return (await client.post("/api/run/segment/answer", json={"answer": correct_answer})).json()


# ---------------------------------------------------------------------------
# Free-text answers: prompt/blank served, accept/answer never in the response
# ---------------------------------------------------------------------------

async def test_question_prompt_and_blank_are_sent_but_the_answer_key_is_not(client):
    config = fast_config()
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    payload = honest_passing_payload(brief, config)
    resp = await client.post(
        "/api/run/segment/game", json={"token": brief["token"], "result": payload}
    )
    body = resp.json()
    assert "prompt" in body["question"]
    assert "blank" in body["question"]
    assert "accept" not in body["question"]
    assert "answer" not in body["question"]
    raw = resp.text
    assert "placeholder1" not in raw  # the accept entry for question 1


async def test_free_text_answer_is_normalised_before_comparison(client):
    config = fast_config()
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    payload = honest_passing_payload(brief, config)
    await client.post(
        "/api/run/segment/game", json={"token": brief["token"], "result": payload}
    )
    accept_entry = config.questions[0].accept[0]
    mangled = f"  {accept_entry.upper()}-!! "
    body = (await client.post(
        "/api/run/segment/answer", json={"answer": mangled}
    )).json()
    # Segment 1 of 4 in act 1: a correct answer advances to segment 2's
    # game, not to a checkpoint (that's only after segment 4).
    assert body["phase"] == "game", "a case/punctuation variant of an accept entry must still pass"
    assert body["segment"] == 2


async def test_wrong_answers_before_the_last_keep_him_on_the_question(client):
    # The whole point of question_attempts: a typo must not cost the segment.
    # Every attempt BUT the last leaves him exactly where he was.
    config = fast_config()
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    payload = honest_passing_payload(brief, config)
    await client.post(
        "/api/run/segment/game", json={"token": brief["token"], "result": payload}
    )

    for spent in range(1, config.question_attempts):
        body = (await client.post(
            "/api/run/segment/answer", json={"answer": "definitely not it"}
        )).json()
        assert body["passed"] is False
        assert body["retry"] is True, f"attempt {spent} must not end the segment"
        assert body["phase"] == "question", "he stays on the question"
        assert body["segment"] == 1
        assert body["question_attempts_left"] == config.question_attempts - spent


async def test_the_last_wrong_answer_restarts_the_whole_segment_in_kiddie(client):
    # ...and the last one still does exactly what it always did.
    config = fast_config()
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    payload = honest_passing_payload(brief, config)
    await client.post(
        "/api/run/segment/game", json={"token": brief["token"], "result": payload}
    )
    for _ in range(config.question_attempts):
        body = (await client.post(
            "/api/run/segment/answer", json={"answer": "definitely not it"}
        )).json()

    assert body["retry"] is False, "the last attempt is a real failure"
    body = (await client.get("/api/run")).json()
    assert body["phase"] == "game", "restart means the game again, not the question"
    assert body["segment"] == 1


async def test_a_correct_answer_after_a_miss_still_clears_the_segment(client):
    # A spent attempt must not poison the question -- getting it right on the
    # second try is a pass, with the segment cleared and the trophy awarded.
    config = fast_config()
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    payload = honest_passing_payload(brief, config)
    await client.post(
        "/api/run/segment/game", json={"token": brief["token"], "result": payload}
    )
    await client.post("/api/run/segment/answer", json={"answer": "definitely not it"})

    answer = config.questions[0].accept[0]
    body = (await client.post("/api/run/segment/answer", json={"answer": answer})).json()
    assert body["passed"] is True
    assert body["retry"] is False
    assert 1 in body["cleared_segments"]
    assert "question-1" in body["trophies"]


async def test_a_fresh_question_restores_the_full_attempt_allowance(client):
    # question_attempts is per-question, never a running total: burning one on
    # segment 1 must not leave him short on segment 2.
    config = fast_config()
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    await client.post(
        "/api/run/segment/game",
        json={"token": brief["token"], "result": honest_passing_payload(brief, config)},
    )
    await client.post("/api/run/segment/answer", json={"answer": "definitely not it"})
    await client.post(
        "/api/run/segment/answer", json={"answer": config.questions[0].accept[0]}
    )

    brief = (await client.post("/api/run/segment/start")).json()
    assert brief["segment"] == 2
    body = (await client.post(
        "/api/run/segment/game",
        json={"token": brief["token"], "result": honest_passing_payload(brief, config)},
    )).json()
    assert body["phase"] == "question"
    assert body["question_attempts_left"] == config.question_attempts


async def test_a_miss_never_costs_a_devil_life(client):
    # The expensive consequences hang off QUESTION_FAILED alone. A typo in
    # Devil mode must cost an attempt and nothing else -- not one of only
    # three lives for the entire run.
    config = fast_config()
    await reach_first_game(client, "devil")
    brief = (await client.post("/api/run/segment/start")).json()
    await client.post(
        "/api/run/segment/game",
        json={"token": brief["token"], "result": honest_passing_payload(brief, config)},
    )
    before = (await client.get("/api/run")).json()["lives"]
    assert before == config.devil_lives

    body = (await client.post(
        "/api/run/segment/answer", json={"answer": "definitely not it"}
    )).json()
    assert body["retry"] is True
    assert body["lives"] == before, "a miss is not a life"

    # ...and the terminal one still is.
    for _ in range(config.question_attempts - 1):
        body = (await client.post(
            "/api/run/segment/answer", json={"answer": "definitely not it"}
        )).json()
    assert body["retry"] is False
    assert body["lives"] == before - 1


async def test_a_wrong_answer_surfaces_its_roast(client):
    # Question.roast (content/schema.py) is authored, validated at
    # content-load time, and used to never reach the player anywhere --
    # eight roasts written for nothing. This is the fix: it comes back on
    # the wrong-answer response, and only there.
    #
    # It lands on the answer that LOSES the segment, not on every near-miss:
    # the roast is the punchline for failing, and firing it three times per
    # question would spend all eight of them in the first minute.
    config = fast_config()
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    payload = honest_passing_payload(brief, config)
    await client.post(
        "/api/run/segment/game", json={"token": brief["token"], "result": payload}
    )
    for _ in range(config.question_attempts - 1):
        body = (await client.post(
            "/api/run/segment/answer", json={"answer": "definitely not it"}
        )).json()
        assert body["roast"] is None, "a survivable miss is not the punchline"

    body = (await client.post(
        "/api/run/segment/answer", json={"answer": "definitely not it"}
    )).json()
    assert body["passed"] is False
    assert body["retry"] is False
    assert body["roast"] == config.questions[brief["segment"] - 1].roast
    assert body["roast"]


async def test_a_correct_answer_carries_no_roast(client):
    config = fast_config()
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    payload = honest_passing_payload(brief, config)
    await client.post(
        "/api/run/segment/game", json={"token": brief["token"], "result": payload}
    )
    correct_answer = config.questions[brief["segment"] - 1].accept[0]
    body = (await client.post(
        "/api/run/segment/answer", json={"answer": correct_answer}
    )).json()
    assert body["passed"] is True
    assert body["roast"] is None


async def test_a_correct_sequence_reported_with_an_impossible_duration_is_rejected(client):
    # Pins that RunService.submit_game actually threads the segment
    # token's issued_at into verify_result -- not just that verify_result
    # itself supports the parameter (xxvi/games/verify.py's own tests cover
    # that). A correct sequence is genuinely solvable in under a
    # millisecond once the seed is known; reporting a duration far beyond
    # any real elapsed time since the token was issued is exactly the
    # "compute it instantly, claim to have taken longer" attack -- and the
    # internal duration/input_count consistency check ALONE (no issued_at)
    # accepts an oversized duration_ms just as happily as a correctly-sized
    # one (see test_games.py::test_without_issued_at_the_wall_clock_check_is_skipped).
    # If a future change drops `issued_at=claim.issued_at` from that call,
    # this becomes GAME_PASSED and this test goes red.
    config = fast_config()
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    payload = honest_passing_payload(brief, config)
    payload["duration_ms"] = 999_999_999  # correct sequence, impossible duration
    response = await client.post(
        "/api/run/segment/game", json={"token": brief["token"], "result": payload}
    )
    assert response.json()["phase"] == "game", "an impossible duration must fail, not pass"


# ---------------------------------------------------------------------------
# Full playthrough: rewards, trophies, and released_rewards vs code_releases
# ---------------------------------------------------------------------------

async def test_clean_run_releases_both_rewards(client):
    config = fast_config()
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
    assert final["released_rewards"] == [1, 2]


async def test_checkpoint_without_operator_approval_advances_but_releases_nothing(
    sessionmaker, settings
):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.sessionmaker = sessionmaker
    config = fast_config()
    app.state.config = config
    # No auto_approve_releases this time -- nobody has approved anything.
    await seed_accounts(sessionmaker, settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
        await reach_first_game(c, "kiddie")
        for _ in range(4):
            await clear_segment(c, config)
        response = await c.post("/api/run/checkpoint", json={"code": CODE})
        body = response.json()
        assert body["outcome"] == "ok"
        assert body["released"] is None
        # The player still advances into act 2 despite no code yet -- checkpoint
        # correctness and reward release are two separate outcomes.
        assert body["run"]["phase"] == "game"
        assert body["run"]["segment"] == 5
        assert body["run"]["released_rewards"] == [], (
            "released_rewards must reflect code_releases, not the state "
            "machine's own act-cleared bookkeeping -- no code was ever "
            "actually emitted here"
        )


async def test_devil_wipe_in_act_two_keeps_reward_one(client):
    config = fast_config()
    await reach_first_game(client, "devil")

    for _ in range(4):
        await clear_segment(client, config)
    await client.post("/api/run/checkpoint", json={"code": CODE})
    await clear_segment(client, config)  # segment 5

    # Fail segments 6, 7, 8 (three lives): the third failure exhausts the pool.
    for _ in range(3):
        brief = (await client.post("/api/run/segment/start")).json()
        await client.post("/api/run/segment/game", json={
            "token": brief["token"], "result": failing_payload(brief_mechanic(config, brief)),
        })

    body = (await client.get("/api/run")).json()
    assert body["segment"] == 1
    assert body["cleared_segments"] == []
    assert body["released_rewards"] == [1], "earned codes are never revoked"
    assert body["trophies"] == []
    assert body["lives"] == 3, "the pool is restored, not left at zero, or the run is unwinnable"


def brief_mechanic(config, brief: dict) -> str:
    return next(g for g in config.games if g.segment == brief["segment"]).mechanic


async def test_devil_failure_with_lives_remaining_replays_in_place_and_keeps_trophies(client):
    # Two consecutive failures, both with lives left afterwards (3 -> 2 -> 1)
    # -- not just the first. An off-by-one in the "does this failure wipe"
    # threshold (e.g. checking `lives <= 2` instead of `lives <= 1`) would
    # only diverge from the correct behaviour on the SECOND failure, when
    # lives-before-failure is exactly 2; a test that only exercises the
    # first failure (3 -> 2) can't distinguish the two thresholds.
    config = fast_config()
    await reach_first_game(client, "devil")
    await clear_segment(client, config)  # segment 1 cleared, trophies earned

    for expected_lives_after in (2, 1):
        brief = (await client.post("/api/run/segment/start")).json()
        assert brief["segment"] == 2
        await client.post("/api/run/segment/game", json={
            "token": brief["token"], "result": failing_payload(brief_mechanic(config, brief)),
        })

        body = (await client.get("/api/run")).json()
        assert body["segment"] == 2, "a failure with lives left replays in place, no wipe"
        assert body["cleared_segments"] == [1]
        assert body["lives"] == expected_lives_after
        assert "game-1" in body["trophies"], "trophies from a cleared segment survive a life loss"


async def test_kiddie_failure_never_touches_lives(client):
    config = fast_config()
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    await client.post("/api/run/segment/game", json={
        "token": brief["token"], "result": failing_payload(brief_mechanic(config, brief)),
    })
    body = (await client.get("/api/run")).json()
    assert body["lives"] is None
    assert body["phase"] == "game"
    assert body["segment"] == 1


# ---------------------------------------------------------------------------
# Token single-use and cross-run isolation
# ---------------------------------------------------------------------------

async def test_a_segment_token_cannot_be_replayed(client):
    config = fast_config()
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    payload = {"token": brief["token"], "result": honest_passing_payload(brief, config)}
    assert (await client.post("/api/run/segment/game", json=payload)).status_code == 200
    assert (await client.post("/api/run/segment/game", json=payload)).status_code == 409


async def test_a_failed_games_token_cannot_be_replayed_either(client):
    # The dangerous replay isn't "submit again after passing" -- the phase
    # guard alone would catch that (phase has moved to QUESTION). It's
    # "fail, then retry the SAME token" while the phase is still GAME: only
    # TokenService's atomic single-use claim blocks this one.
    config = fast_config()
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    payload = {
        "token": brief["token"],
        "result": failing_payload(brief_mechanic(config, brief)),
    }
    first = await client.post("/api/run/segment/game", json=payload)
    assert first.status_code == 200
    assert first.json()["phase"] == "game"  # failed, still at a game
    second = await client.post("/api/run/segment/game", json=payload)
    assert second.status_code == 409


async def test_a_segment_token_minted_for_one_run_is_rejected_by_another(
    sessionmaker, settings
):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.sessionmaker = sessionmaker
    config = fast_config()
    app.state.config = config
    app.state.auto_approve_releases = True
    await seed_accounts(sessionmaker, settings)

    from sqlalchemy import select as sa_select
    from xxvi.persistence.models import Account
    async with sessionmaker() as session:
        session.add(Account(username="her", password_hash=hash_password("pw2"), role="player"))
        await session.commit()
        result = await session.execute(sa_select(Account).where(Account.username == "her"))
        assert result.scalar_one() is not None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as him, \
            AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as her:
        await him.post("/api/auth/login", json={"username": "him", "password": "pw"})
        await reach_first_game(him, "kiddie")
        brief = (await him.post("/api/run/segment/start")).json()

        await her.post("/api/auth/login", json={"username": "her", "password": "pw2"})
        await reach_first_game(her, "kiddie")
        payload = {"token": brief["token"], "result": honest_passing_payload(brief, config)}
        response = await her.post("/api/run/segment/game", json=payload)
        assert response.status_code == 409


# ---------------------------------------------------------------------------
# Phase guards on every mutating route
# ---------------------------------------------------------------------------

async def test_submitting_a_game_while_at_a_question_is_rejected(client):
    config = fast_config()
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    payload = {"token": brief["token"], "result": honest_passing_payload(brief, config)}
    first = await client.post("/api/run/segment/game", json=payload)
    assert first.json()["phase"] == "question"  # now at the question

    # Any further game submission -- even with a garbage token -- must be
    # rejected by the phase guard before it ever touches token validation.
    response = await client.post(
        "/api/run/segment/game", json={"token": "garbage", "result": payload["result"]}
    )
    assert response.status_code == 409


async def test_a_legitimate_but_stale_token_while_at_a_question_is_also_rejected(
    client, sessionmaker
):
    # The dangerous case isn't a garbage token (that 409s via token
    # validation regardless of the phase guard). It's a technically VALID,
    # never-before-consumed token for the current run/segment submitted
    # while the player has already moved on to the question. `advance()`
    # itself tolerates a GAME_FAILED event arriving from Phase.QUESTION
    # (`_FAILURES` accepts both GAME and QUESTION) -- so without the
    # route's own phase guard, this doesn't 500, it silently succeeds and
    # knocks a player who already passed the game back into it. Only the
    # explicit `if state.phase is not Phase.GAME` check in the route
    # catches this.
    from sqlalchemy import select

    from xxvi.games.tokens import issue_segment_token
    from xxvi.persistence.models import Run

    config = fast_config()
    await reach_first_game(client, "kiddie")
    brief = (await client.post("/api/run/segment/start")).json()
    payload = {"token": brief["token"], "result": honest_passing_payload(brief, config)}
    first = await client.post("/api/run/segment/game", json=payload)
    assert first.json()["phase"] == "question"  # now at the question

    async with sessionmaker() as session:
        run = (await session.execute(select(Run))).scalars().one()
    fresh_token, fresh_seed = issue_segment_token(run.id, 1)

    response = await client.post(
        "/api/run/segment/game",
        json={
            "token": fresh_token,
            "result": {"mechanic": "simon", "passed_client_side": False,
                       "duration_ms": 1, "input_count": 1, "score": 0, "sequence": [0]},
        },
    )
    assert response.status_code == 409
    body = (await client.get("/api/run")).json()
    assert body["phase"] == "question", "a stale-but-valid token must not knock a player back"


async def test_a_checkpoint_submission_mid_segment_is_rejected(client):
    await reach_first_game(client, "kiddie")
    response = await client.post("/api/run/checkpoint", json={"code": CODE})
    assert response.status_code == 409


async def test_an_answer_submission_outside_a_question_is_rejected(client):
    await reach_first_game(client, "kiddie")
    response = await client.post("/api/run/segment/answer", json={"answer": "anything"})
    assert response.status_code == 409


async def test_a_game_start_outside_the_game_phase_is_rejected(client):
    await client.post("/api/run/activate", json={"code": CODE})
    response = await client.post("/api/run/segment/start")
    assert response.status_code == 409


async def test_activation_twice_is_rejected(client):
    await client.post("/api/run/activate", json={"code": CODE})
    response = await client.post("/api/run/activate", json={"code": CODE})
    assert response.status_code == 409


async def test_profile_out_of_order_is_rejected(client):
    # Never activated -- still at ACTIVATION, not PROFILE.
    response = await client.post("/api/run/profile")
    assert response.status_code == 409


async def test_no_accept_entry_ever_appears_in_any_run_response_body(client):
    # Scans every response text encountered along a full clean run for any
    # of the 8 questions' accept-list entries. A leak anywhere here --
    # /api/run, a game submission response, an answer response, the
    # checkpoint response -- would mean the answer key reached the client.
    config = fast_config()
    forbidden = [entry for q in config.questions for entry in q.accept]

    seen_texts: list[str] = []
    await reach_first_game(client, "kiddie")
    seen_texts.append((await client.get("/api/run")).text)
    for _ in range(4):
        brief_resp = await client.post("/api/run/segment/start")
        seen_texts.append(brief_resp.text)
        brief = brief_resp.json()
        game_resp = await client.post(
            "/api/run/segment/game",
            json={"token": brief["token"], "result": honest_passing_payload(brief, config)},
        )
        seen_texts.append(game_resp.text)
        seen_texts.append((await client.get("/api/run")).text)
        correct_answer = config.questions[brief["segment"] - 1].accept[0]
        answer_resp = await client.post(
            "/api/run/segment/answer", json={"answer": correct_answer}
        )
        seen_texts.append(answer_resp.text)
    checkpoint_resp = await client.post("/api/run/checkpoint", json={"code": CODE})
    seen_texts.append(checkpoint_resp.text)

    blob = "\n".join(seen_texts)
    for entry in forbidden:
        assert entry not in blob, f"accept entry {entry!r} leaked into a response body"


async def test_the_run_endpoint_requires_a_signed_in_player(sessionmaker, settings):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.sessionmaker = sessionmaker
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as anon:
        assert (await anon.get("/api/run")).status_code == 401


async def test_a_checkpoint_still_shows_the_code_when_it_was_released_early(
    sessionmaker, settings
):
    """The payoff moment must never be blank.

    Observed live: the operator released reward 1 from the dashboard while
    the player was still on the checkpoint screen. He then entered the
    correct checkpoint code, the run advanced -- and `released` came back
    `null`, so the gift card he had just earned never appeared. The
    dashboard meanwhile reported "the player already has the code", which he
    did not: the `code_released` WebSocket broadcast fired at release time,
    is a one-shot with no redelivery, and he was on another screen.

    Re-showing it is not a second emission -- the `code_releases` ledger is
    what raised AlreadyReleased in the first place, so a row for exactly this
    (run, reward) provably exists and the unique constraint is untouched.
    """
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.sessionmaker = sessionmaker
    config = fast_config()
    app.state.config = config
    app.state.auto_approve_releases = True  # operator stand-in, as in `client`
    await seed_accounts(sessionmaker, settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        await c.post("/api/auth/login", json={"username": "him", "password": "pw"})
        await reach_first_game(c, "kiddie")
        for _ in range(4):
            await clear_segment(c, config)

        # The operator gets there first, out of band -- the dashboard's
        # "release reward 1" button, pressed while he is still typing.
        run_id = await only_run_id(sessionmaker)
        vault = VaultService(sessionmaker, settings)
        early = await vault.release(run_id, 1, approved_by_operator=True)

        body = (await c.post("/api/run/checkpoint", json={"code": CODE})).json()

        assert body["outcome"] == "ok"
        assert body["run"]["phase"] == "game", "he still advances"
        assert body["released"] is not None, (
            "a blank screen at the reveal is the worst possible outcome"
        )
        assert body["released"]["code"] == early, "the same code he was already owed"
        assert body["released"]["reward_id"] == 1

        # ...and still exactly one row in the ledger: nothing was re-emitted.
        assert await vault.released_reward_ids(run_id) == frozenset({1})


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

async def test_the_profile_reports_the_run_so_far(client):
    config = fast_config()
    await reach_first_game(client, "kiddie")
    await clear_segment(client, config)

    body = (await client.get("/api/run/profile")).json()

    assert body["recipient"] == config.recipient
    assert body["difficulty"] == "kiddie"
    assert body["total_segments"] == config.total_segments
    assert body["cleared"] == 1
    assert body["started_at"]
    assert "game-1" in body["trophies"] and "question-1" in body["trophies"]

    assert len(body["answered"]) == 1
    assert body["answered"][0]["segment"] == 1
    assert body["answered"][0]["prompt"] == config.questions[0].prompt
    assert body["answered"][0]["answer"] == config.questions[0].accept[0]


async def test_the_profile_never_reveals_an_unanswered_question(client):
    """The whole risk of a profile screen: it is the one place holding both
    the questions and their answers. It may only ever describe segments he
    has already cleared -- otherwise it hands him the rest of the run."""
    config = fast_config()
    await reach_first_game(client, "kiddie")
    await clear_segment(client, config)

    response = await client.get("/api/run/profile")
    raw = response.text

    assert response.json()["answered"] == response.json()["answered"][:1]
    for question in config.questions[1:]:
        assert question.accept[0] not in raw, (
            f"answer to an uncleared question leaked: {question.accept[0]!r}"
        )
        assert question.prompt not in raw


async def test_the_profile_is_empty_before_anything_is_cleared(client):
    await reach_first_game(client, "devil")
    body = (await client.get("/api/run/profile")).json()
    assert body["answered"] == []
    assert body["cleared"] == 0
    assert body["lives"] == fast_config().devil_lives

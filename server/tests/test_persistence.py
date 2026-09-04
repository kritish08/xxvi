from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from xxvi.core.machine import advance
from xxvi.core.models import Difficulty, Event, Phase, RunState, Shape, initial_state
from xxvi.persistence.models import Account, CodeRelease, RunEvent
from xxvi.persistence.repositories import RunRepository

SHAPE = Shape(acts=2, segments_per_act=4)

# save_state is now `save_state(run_id, expected_version, state) -> bool`, a
# compare-and-swap keyed on Run.version rather than a plain load-assign-commit
# (see the method's own docstring and alembic/versions/0004_run_version.py
# for why: the old shape produced torn rows under concurrent writes). Every
# call below passes the freshly-created `run`'s own `.version` -- there is no
# concurrent writer in any of these single-threaded tests, so the CAS always
# succeeds; the return value isn't asserted here because that's covered by
# the dedicated concurrency tests in tests/test_run_service_concurrency.py.


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
    await repo.save_state(run.id, run.version, state)

    reloaded = await repo.get_by_account(account.id)
    assert reloaded.phase == "question"
    assert reloaded.segment == 5
    assert sorted(reloaded.cleared_segments) == [1, 2, 3, 4]
    assert reloaded.released_rewards == [1]


# --- The load-bearing difficulty write. Every other test in this file creates
# a run with its final difficulty already set, so `run.difficulty = ...` in
# save_state is never observed changing anything by those tests alone. The
# real production path is create(account_id, None) -> player picks a
# difficulty -> advance(DIFFICULTY_CHOSEN) -> save_state. If that write
# regressed, runs.difficulty stays NULL forever, to_state() yields
# difficulty=None, and _apply_failure raises on every failure event at
# midnight — the exact failure mode this whole task exists to prevent.
async def test_save_state_persists_difficulty_chosen_via_the_real_transition_path(
    sessionmaker, account
):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, None)
    assert run.difficulty is None

    state = initial_state()
    state = advance(state, Event.ACTIVATED, SHAPE)
    state = advance(state, Event.PROFILE_CHOSEN, SHAPE)
    state = advance(state, Event.DIFFICULTY_CHOSEN, SHAPE, difficulty=Difficulty.DEVIL,
                     devil_lives=3)
    assert state.difficulty is Difficulty.DEVIL

    await repo.save_state(run.id, run.version, state)

    reloaded = await repo.get_by_account(account.id)
    assert reloaded.difficulty == "devil"
    assert reloaded.lives == 3


# The brief's own {1,2,3,4} fixture iterates in already-sorted order under
# CPython's small-int hashing, so `list(state.cleared_segments)` (no sort)
# would pass the test above by coincidence. {8, 1, 17} does not iterate
# sorted, so this pins that `save_state` actually calls `sorted()` and not
# just `list()`.
# --- Devil lives round trip. save_state must write RunState.lives to the
# `lives` column and to_state must read it back, or a DEVIL player's
# remaining-lives count silently resets to None (and _apply_failure's
# fail-closed guard rejects the very next failure event) every time their
# state is reloaded from the database.
async def test_save_state_persists_lives_and_to_state_rehydrates_them(sessionmaker, account):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.DEVIL)
    state = RunState(
        phase=Phase.GAME, difficulty=Difficulty.DEVIL, segment=4,
        cleared_segments=frozenset({1, 2, 3}), released_rewards=frozenset(), lives=2,
    )
    await repo.save_state(run.id, run.version, state)

    reloaded = await repo.get_by_account(account.id)
    assert reloaded.lives == 2

    rehydrated = RunRepository.to_state(reloaded)
    assert rehydrated.lives == 2


# --- LOAD-BEARING round trip, devil branch: a DEVIL state saved and reloaded
# through the repository must remain usable by advance() on a failure event
# with the life-decrement semantics, not just the KIDDIE branch already
# covered by test_state_round_trips_through_repository_and_stays_usable_by_advance.
async def test_devil_state_round_trips_through_repository_and_decrements_lives_on_failure(
    sessionmaker, account
):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.DEVIL)
    state = RunState(
        phase=Phase.GAME, difficulty=Difficulty.DEVIL, segment=3,
        cleared_segments=frozenset({1, 2}), released_rewards=frozenset(), lives=3,
    )
    await repo.save_state(run.id, run.version, state)

    reloaded = await repo.get_by_account(account.id)
    rehydrated = RunRepository.to_state(reloaded)

    result = advance(rehydrated, Event.GAME_FAILED, SHAPE, devil_lives=3)
    assert result.lives == 2
    assert result.segment == 3, "lives remaining -- replay in place, not a wipe"
    assert result.cleared_segments == frozenset({1, 2})


async def test_save_state_writes_cleared_segments_and_rewards_in_sorted_order(
    sessionmaker, account
):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.DEVIL)
    state = RunState(
        phase=Phase.GAME, difficulty=Difficulty.DEVIL, segment=18,
        cleared_segments=frozenset({8, 1, 17}), released_rewards=frozenset({50, 2, 100}),
    )
    await repo.save_state(run.id, run.version, state)

    reloaded = await repo.get_by_account(account.id)
    assert reloaded.cleared_segments == [1, 8, 17]
    assert reloaded.released_rewards == [2, 50, 100]


async def test_awarding_a_trophy_twice_is_idempotent(sessionmaker, account):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    assert await repo.award_trophy(run.id, "game-1") is True
    assert await repo.award_trophy(run.id, "game-1") is False
    assert await repo.earned_trophies(run.id) == frozenset({"game-1"})


# --- earned_trophies must be scoped by run_id at the query, not merely by
# which trophies happen to exist. With only one run in play (as above), a
# dropped run_id filter is invisible. Two runs, disjoint trophies, cross-check.
async def test_earned_trophies_only_returns_its_own_run(sessionmaker, account, account2):
    repo = RunRepository(sessionmaker)
    run_a = await repo.create(account.id, Difficulty.KIDDIE)
    run_b = await repo.create(account2.id, Difficulty.KIDDIE)

    await repo.award_trophy(run_a.id, "game-1")
    await repo.award_trophy(run_b.id, "game-2")

    assert await repo.earned_trophies(run_a.id) == frozenset({"game-1"})
    assert await repo.earned_trophies(run_b.id) == frozenset({"game-2"})


async def test_clearing_segment_trophies_keeps_hidden_ones(sessionmaker, account):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.DEVIL)
    for trophy in ("game-1", "question-1", "act-1", "hidden-rage-quit"):
        await repo.award_trophy(run.id, trophy)

    await repo.clear_segment_trophies(run.id)
    assert await repo.earned_trophies(run.id) == frozenset({"hidden-rage-quit"})


# --- HIDDEN_PREFIX matching must be a prefix check, not a substring check.
# "act-2-hidden-bonus" contains "hidden-" but does not start with it, so it
# is not a hidden trophy and must be wiped. A prior commit closed this exact
# gap in core/trophies.py; this pins the same requirement in its persistence
# mirror, clear_segment_trophies.
async def test_clear_segment_trophies_is_a_prefix_match_not_a_substring_match(
    sessionmaker, account
):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.DEVIL)
    await repo.award_trophy(run.id, "act-2-hidden-bonus")
    await repo.award_trophy(run.id, "hidden-rage-quit")

    await repo.clear_segment_trophies(run.id)

    assert await repo.earned_trophies(run.id) == frozenset({"hidden-rage-quit"})


# --- clear_segment_trophies is the worst-shaped run-scoping gap: without its
# run_id filter, wiping one run's segment trophies (a Devil failure) would
# delete every OTHER run's non-hidden trophies too. Two runs, act on one,
# assert the other is untouched.
async def test_clear_segment_trophies_only_affects_its_own_run(
    sessionmaker, account, account2
):
    repo = RunRepository(sessionmaker)
    run_a = await repo.create(account.id, Difficulty.DEVIL)
    run_b = await repo.create(account2.id, Difficulty.DEVIL)

    for run in (run_a, run_b):
        await repo.award_trophy(run.id, "game-1")
        await repo.award_trophy(run.id, "question-1")

    await repo.clear_segment_trophies(run_a.id)

    assert await repo.earned_trophies(run_a.id) == frozenset()
    assert await repo.earned_trophies(run_b.id) == frozenset({"game-1", "question-1"})


async def test_events_are_appended_and_searchable(sessionmaker, account):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    await repo.append_event(run.id, "token_consumed", {"nonce": "abc"})

    assert await repo.has_event(run.id, "token_consumed", {"nonce": "abc"}) is True
    assert await repo.has_event(run.id, "token_consumed", {"nonce": "zzz"}) is False


# --- run_events is append-only by explicit global constraint. Nothing else
# in this file appends more than one event, so an upsert (collapsing same-kind
# events into one row) or a delete-then-insert (clearing prior events of that
# kind before writing the new one) would both survive undetected. This drives
# several events, including two of the *same* kind with different payloads,
# and asserts every row is still present, in append order, none overwritten.
async def test_append_event_is_append_only_never_overwrites_or_collapses(
    sessionmaker, account
):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)

    await repo.append_event(run.id, "token_consumed", {"nonce": "abc"})
    await repo.append_event(run.id, "token_consumed", {"nonce": "def"})
    await repo.append_event(run.id, "game_passed", {"segment": 1})

    async with sessionmaker() as session:
        result = await session.execute(
            select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.id)
        )
        rows = result.scalars().all()

    assert [(row.kind, row.payload) for row in rows] == [
        ("token_consumed", {"nonce": "abc"}),
        ("token_consumed", {"nonce": "def"}),
        ("game_passed", {"segment": 1}),
    ]


# --- LOAD-BEARING round trip: a state saved and reloaded through the
# repository must be usable by advance() on a failure event, not raise.
# machine._apply_failure compares state.difficulty with `is`, so a naive
# rehydration that passes the raw DB string straight into RunState would
# raise InvalidTransition on every failure event instead of applying the
# KIDDIE-restart / DEVIL-wipe rule. RunRepository.to_state() must construct
# real enum members to avoid that.
async def test_state_round_trips_through_repository_and_stays_usable_by_advance(
    sessionmaker, account
):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.KIDDIE)
    state = RunState(
        phase=Phase.GAME, difficulty=Difficulty.KIDDIE, segment=3,
        cleared_segments=frozenset({1, 2}), released_rewards=frozenset(),
    )
    await repo.save_state(run.id, run.version, state)

    reloaded = await repo.get_by_account(account.id)
    rehydrated = RunRepository.to_state(reloaded)

    result = advance(rehydrated, Event.GAME_FAILED, SHAPE)
    assert result.phase is Phase.GAME
    assert result.segment == 3
    assert result.cleared_segments == frozenset({1, 2}), "kiddie restart keeps prior clears"


# --- has_event must be scoped by run_id, not just kind+payload. With only one
# run in play, a dropped run_id filter is invisible.
async def test_has_event_only_checks_its_own_run(sessionmaker, account, account2):
    repo = RunRepository(sessionmaker)
    run_a = await repo.create(account.id, Difficulty.KIDDIE)
    run_b = await repo.create(account2.id, Difficulty.KIDDIE)

    await repo.append_event(run_b.id, "token_consumed", {"nonce": "abc"})

    assert await repo.has_event(run_b.id, "token_consumed", {"nonce": "abc"}) is True
    assert await repo.has_event(run_a.id, "token_consumed", {"nonce": "abc"}) is False


async def test_get_by_account_returns_the_matching_run_not_the_first_one(sessionmaker):
    async with sessionmaker() as session:
        alice = Account(username="alice", password_hash="x", role="player")
        bob = Account(username="bob", password_hash="x", role="player")
        session.add_all([alice, bob])
        await session.commit()
        alice_id, bob_id = alice.id, bob.id

    repo = RunRepository(sessionmaker)
    alice_run = await repo.create(alice_id, Difficulty.KIDDIE)
    bob_run = await repo.create(bob_id, Difficulty.DEVIL)
    assert alice_run.id != bob_run.id

    reloaded_bob = await repo.get_by_account(bob_id)
    assert reloaded_bob is not None
    assert reloaded_bob.id == bob_run.id
    assert reloaded_bob.difficulty == "devil"

    reloaded_alice = await repo.get_by_account(alice_id)
    assert reloaded_alice.id == alice_run.id
    assert reloaded_alice.difficulty == "kiddie"


# --- Gift-card codes are never stored; only the fact of a release is. That
# fact must be one-time per (run, reward) at the DB level, not merely by
# application discipline — this pins the UNIQUE constraint on code_releases.
async def test_code_release_is_unique_per_run_and_reward(sessionmaker, account):
    repo = RunRepository(sessionmaker)
    run = await repo.create(account.id, Difficulty.DEVIL)

    async with sessionmaker() as session:
        session.add(CodeRelease(run_id=run.id, reward_id=1))
        await session.commit()

    async with sessionmaker() as session:
        session.add(CodeRelease(run_id=run.id, reward_id=1))
        try:
            await session.commit()
            raised = False
        except IntegrityError:
            await session.rollback()
            raised = True
    assert raised, "a second release of the same reward for the same run must be rejected"

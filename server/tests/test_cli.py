"""Tests for xxvi/cli.py: the operator's dashboard-independent fallback.

Also asserts, statically, that this module never imports the HTTP layer or
the realtime hub -- it exists precisely for the moment those are broken.
"""

import ast
from pathlib import Path

import pytest
from sqlalchemy import select

import xxvi.cli as cli_module
from xxvi.cli import cmd_validate_config
from xxvi.auth.passwords import hash_password
from xxvi.content.schema import RunConfig
from xxvi.core.models import Difficulty
from xxvi.persistence.models import Run
from xxvi.persistence.repositories import RunRepository
from xxvi.settings import ConfigNotProductionReady, Settings
from xxvi.vault.service import VaultService

CLI_SOURCE_PATH = Path(cli_module.__file__)

FORBIDDEN_MODULE_PREFIXES = ("fastapi", "starlette", "xxvi.main", "xxvi.api", "xxvi.realtime")


def _production_ready_settings(**overrides) -> Settings:
    base = dict(
        database_url="postgresql+asyncpg://neondb_owner:x@ep-real.neon.tech/neondb",
        reward_1_code="REAL-0001", reward_2_code="REAL-0002",
        session_secret="a-genuinely-random-secret-not-the-dev-default-x7q2",
        player_password_hash=hash_password("pw"),
        operator_password_hash=hash_password("pw"),
        activation_code_hash=hash_password("ACTIVATE"),
        checkpoint_1_hash=hash_password("CHECK1"),
        checkpoint_2_hash=hash_password("CHECK2"),
    )
    base.update(overrides)
    return Settings(**base)


def test_cli_module_imports_nothing_from_the_http_layer_or_the_hub():
    # Static check, not a runtime import trace: the CLI must never even be
    # ABLE to pull in fastapi/starlette/xxvi.main/xxvi.api/xxvi.realtime,
    # since that's the exact stack this module exists to survive the
    # breakage of. A parse-level check catches this regardless of whether
    # any particular test run happens to exercise the offending import path.
    tree = ast.parse(CLI_SOURCE_PATH.read_text())
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)

    for name in imported_names:
        assert not name.startswith(FORBIDDEN_MODULE_PREFIXES), (
            f"xxvi/cli.py imports {name!r} -- forbidden, see module docstring"
        )


def test_normalize_activation_candidate_matches_the_clients_formatKey():
    # Must mirror web/src/shell/Activation.tsx's formatKey exactly: upper,
    # strip non-alphanumerics, group into 4s.
    assert cli_module._normalize_activation_candidate("answerword12") == "ANSW-ERWO-RD12"
    assert cli_module._normalize_activation_candidate("ANSW-ERWO-RD12") == "ANSW-ERWO-RD12"
    assert cli_module._normalize_activation_candidate("  Answer Word12 ") == "ANSW-ERWO-RD12"


def test_normalize_activation_candidate_refuses_a_length_the_client_could_never_produce():
    # Activation.tsx's submit button only ever enables for exactly 12
    # alphanumerics (KEY_PATTERN) -- anything else must be refused, not
    # silently truncated or padded into a hash that could never verify.
    assert cli_module._normalize_activation_candidate("tooshort") is None
    assert cli_module._normalize_activation_candidate("way-too-long-an-answer-here") is None


def test_hash_secret_activation_mode_refuses_an_answer_that_is_not_12_characters(
    monkeypatch, capsys
):
    monkeypatch.setattr("getpass.getpass", lambda *_: "too short")
    with pytest.raises(SystemExit) as exc:
        cli_module.cmd_hash_secret(activation=True)
    assert exc.value.code != 0
    assert "refused" in capsys.readouterr().out


def test_hash_secret_activation_mode_shows_the_literal_string_being_hashed(monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda *_: "answerword12")
    cli_module.cmd_hash_secret(activation=True)
    out = capsys.readouterr().out
    assert "ANSW-ERWO-RD12" in out


async def test_hash_secret_activation_mode_round_trips_through_the_real_gate(
    monkeypatch, capsys, sessionmaker, account
):
    # Ship-blocking finding, reproduced end to end (task-30 review): the
    # activation gate compares candidate.strip().upper() (gates/service.py)
    # -- dashes stripped on NEITHER side -- against whatever hash-secret
    # hashed, but the client (Activation.tsx) always POSTs the dashed
    # XXXX-XXXX-XXXX form. Hashing a bare-typed riddle answer through the
    # generic hash-secret path (verified directly: hash_password("ANSWERWORD12")
    # does not verify against "ANSW-ERWO-RD12") minted a hash the real
    # client could never satisfy -- activation would fail forever with no
    # operator bypass. This proves --activation mode fixes that, driven
    # through the actual GateService, not a hand-rolled comparison.
    from xxvi.gates.service import GateId, GateOutcome, GateService

    monkeypatch.setattr("getpass.getpass", lambda *_: "answerword12")  # typed with no dashes
    cli_module.cmd_hash_secret(activation=True)
    minted_hash = capsys.readouterr().out.strip().splitlines()[-1]

    settings = Settings(activation_code_hash=minted_hash)
    run = await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)
    service = GateService(RunRepository(sessionmaker), settings)

    # Exactly what Activation.tsx's formatKey produces and POSTs.
    assert await service.submit(run.id, GateId.ACTIVATION, "ANSW-ERWO-RD12") is GateOutcome.OK


async def test_cmd_release_emits_a_real_code_with_production_ready_config(
    sessionmaker, account, monkeypatch
):
    settings = _production_ready_settings()
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: sessionmaker)

    run = await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)
    await cli_module.cmd_release(run.id, 1, skip_confirmation=True)

    vault = VaultService(sessionmaker, settings)
    assert await vault.released_reward_ids(run.id) == frozenset({1})


async def test_cmd_release_refuses_a_dummy_reward_code(sessionmaker, account, monkeypatch, capsys):
    settings = _production_ready_settings(reward_1_code="DUMMY-REWARD-0001")
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: sessionmaker)

    run = await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)
    with pytest.raises(ConfigNotProductionReady):
        await cli_module.cmd_release(run.id, 1, skip_confirmation=True)

    # Nothing should have been released -- the refusal must happen before
    # any vault interaction, not after a code already went out.
    vault = VaultService(sessionmaker, settings)
    assert await vault.released_reward_ids(run.id) == frozenset()


async def test_cmd_release_refuses_under_dry_run(sessionmaker, account, monkeypatch):
    # CRITICAL, reproduced end to end: DRY_RUN=true release --run 1 --reward 1
    # used to print DRY-RUN-REWARD-1 at exit 0, looking like a real release
    # succeeded, on an otherwise fully production-ready config.
    settings = _production_ready_settings(dry_run=True)
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: sessionmaker)

    run = await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)
    with pytest.raises(ConfigNotProductionReady):
        await cli_module.cmd_release(run.id, 1, skip_confirmation=True)

    vault = VaultService(sessionmaker, settings)
    assert await vault.released_reward_ids(run.id) == frozenset()


async def test_cmd_release_without_confirmation_releases_nothing(
    sessionmaker, account, monkeypatch
):
    settings = _production_ready_settings()
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: sessionmaker)
    monkeypatch.setattr("builtins.input", lambda *_: "no")  # operator declines

    run = await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)
    await cli_module.cmd_release(run.id, 1, skip_confirmation=False)

    vault = VaultService(sessionmaker, settings)
    assert await vault.released_reward_ids(run.id) == frozenset()


async def test_cmd_release_with_typed_confirmation_releases(sessionmaker, account, monkeypatch):
    settings = _production_ready_settings()
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: sessionmaker)
    monkeypatch.setattr("builtins.input", lambda *_: "yes")

    run = await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)
    await cli_module.cmd_release(run.id, 1, skip_confirmation=False)

    vault = VaultService(sessionmaker, settings)
    assert await vault.released_reward_ids(run.id) == frozenset({1})


def test_check_config_command_reports_not_ready_and_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(cli_module, "get_settings", lambda: Settings())
    with pytest.raises(SystemExit) as exc:
        cli_module.cmd_check_config()
    assert exc.value.code != 0
    assert "NOT ready" in capsys.readouterr().out


def test_check_config_command_reports_ready(monkeypatch, capsys):
    from xxvi.content.schema import RunConfig

    monkeypatch.setattr(cli_module, "get_settings", lambda: _production_ready_settings())
    # This repo checkout has no real config/run.yaml (it's gitignored,
    # volume-mounted on the real box) -- fake a real one being present so
    # this test exercises Settings-readiness in isolation, the same
    # boundary it always had. The example-fallback and content-placeholder
    # cases each get their own dedicated test below.
    monkeypatch.setattr(cli_module, "is_serving_example_content", lambda: False)
    monkeypatch.setattr(
        cli_module,
        "get_config",
        lambda: RunConfig.model_validate(
            {
                "recipient": "Real Name",
                "acts": 1,
                "segments_per_act": 1,
                "questions": [{"prompt": "a real question", "accept": ["a"], "roast": "r"}],
                "games": [{"segment": 1, "mechanic": "simon", "params": {}}],
                "trophies": [
                    {"id": "game-1", "name": "n", "grade": "bronze"},
                    {"id": "question-1", "name": "n", "grade": "bronze"},
                    {"id": "act-1", "name": "n", "grade": "gold"},
                    {"id": "platinum", "name": "n", "grade": "platinum"},
                ],
                "rewards": [{"id": 1, "after_act": 1, "label": "r"}],
                "copy": {"coming_soon": "a", "teaser": "b", "how_to_play": "c", "closing": "d"},
            }
        ),
    )
    cli_module.cmd_check_config()  # must not raise
    assert "OK" in capsys.readouterr().out


def test_check_config_command_refuses_when_serving_example_content(monkeypatch, capsys):
    # Ship-blocking finding, reproduced end to end (task-30 review):
    # check-config only ever validated Settings -- a missing
    # config/run.yaml made get_config() silently fall back to
    # run.example.yaml, and check-config said "config OK" anyway, right
    # before the real run asked "Q1 placeholder" and expected
    # "placeholder1". Must now refuse loudly instead.
    monkeypatch.setattr(cli_module, "get_settings", lambda: _production_ready_settings())
    monkeypatch.setattr(cli_module, "is_serving_example_content", lambda: True)
    with pytest.raises(SystemExit) as exc:
        cli_module.cmd_check_config()
    assert exc.value.code != 0
    out = capsys.readouterr().out
    assert "NOT ready" in out
    assert "run.example.yaml" in out


def test_check_config_command_refuses_a_placeholder_recipient(monkeypatch, capsys):
    from xxvi.content.schema import RunConfig

    monkeypatch.setattr(cli_module, "get_settings", lambda: _production_ready_settings())
    monkeypatch.setattr(cli_module, "is_serving_example_content", lambda: False)
    config = RunConfig.model_validate(
        {
            "recipient": "PLACEHOLDER",
            "acts": 1,
            "segments_per_act": 1,
            "questions": [{"prompt": "a real question", "accept": ["a"], "roast": "r"}],
            "games": [{"segment": 1, "mechanic": "simon", "params": {}}],
            "trophies": [
                {"id": "game-1", "name": "n", "grade": "bronze"},
                {"id": "question-1", "name": "n", "grade": "bronze"},
                {"id": "act-1", "name": "n", "grade": "gold"},
                {"id": "platinum", "name": "n", "grade": "platinum"},
            ],
            "rewards": [{"id": 1, "after_act": 1, "label": "r"}],
            "copy": {"coming_soon": "a", "teaser": "b", "how_to_play": "c", "closing": "d"},
        }
    )
    monkeypatch.setattr(cli_module, "get_config", lambda: config)
    with pytest.raises(SystemExit) as exc:
        cli_module.cmd_check_config()
    assert exc.value.code != 0
    assert "recipient" in capsys.readouterr().out


def test_check_config_command_refuses_a_placeholder_question_prompt(monkeypatch, capsys):
    from xxvi.content.schema import RunConfig

    monkeypatch.setattr(cli_module, "get_settings", lambda: _production_ready_settings())
    monkeypatch.setattr(cli_module, "is_serving_example_content", lambda: False)
    config = RunConfig.model_validate(
        {
            "recipient": "Real Name",
            "acts": 1,
            "segments_per_act": 1,
            "questions": [{"prompt": "Q1 placeholder", "accept": ["a"], "roast": "r"}],
            "games": [{"segment": 1, "mechanic": "simon", "params": {}}],
            "trophies": [
                {"id": "game-1", "name": "n", "grade": "bronze"},
                {"id": "question-1", "name": "n", "grade": "bronze"},
                {"id": "act-1", "name": "n", "grade": "gold"},
                {"id": "platinum", "name": "n", "grade": "platinum"},
            ],
            "rewards": [{"id": 1, "after_act": 1, "label": "r"}],
            "copy": {"coming_soon": "a", "teaser": "b", "how_to_play": "c", "closing": "d"},
        }
    )
    monkeypatch.setattr(cli_module, "get_config", lambda: config)
    with pytest.raises(SystemExit) as exc:
        cli_module.cmd_check_config()
    assert exc.value.code != 0
    out = capsys.readouterr().out
    assert "question 1 prompt" in out
    assert "Q1 placeholder" in out


def test_check_config_command_passes_with_real_content(monkeypatch, capsys):
    from xxvi.content.schema import RunConfig

    monkeypatch.setattr(cli_module, "get_settings", lambda: _production_ready_settings())
    monkeypatch.setattr(cli_module, "is_serving_example_content", lambda: False)
    config = RunConfig.model_validate(
        {
            "recipient": "Real Name",
            "acts": 1,
            "segments_per_act": 1,
            "questions": [{"prompt": "a real question", "accept": ["a"], "roast": "r"}],
            "games": [{"segment": 1, "mechanic": "simon", "params": {}}],
            "trophies": [
                {"id": "game-1", "name": "n", "grade": "bronze"},
                {"id": "question-1", "name": "n", "grade": "bronze"},
                {"id": "act-1", "name": "n", "grade": "gold"},
                {"id": "platinum", "name": "n", "grade": "platinum"},
            ],
            "rewards": [{"id": 1, "after_act": 1, "label": "r"}],
            "copy": {"coming_soon": "a", "teaser": "b", "how_to_play": "c", "closing": "d"},
        }
    )
    monkeypatch.setattr(cli_module, "get_config", lambda: config)
    cli_module.cmd_check_config()  # must not raise
    assert "OK" in capsys.readouterr().out


def test_check_config_command_refuses_under_dry_run(monkeypatch, capsys):
    # CRITICAL, reproduced end to end: DRY_RUN=true check-config used to say
    # "config OK" right before DRY_RUN=true release burned the real reward.
    # An otherwise-production-ready config with dry_run still on must refuse.
    settings = _production_ready_settings(dry_run=True)
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    with pytest.raises(SystemExit) as exc:
        cli_module.cmd_check_config()
    assert exc.value.code != 0
    assert "NOT ready" in capsys.readouterr().out


async def test_cmd_state_reports_code_releases_not_released_rewards(
    sessionmaker, account, monkeypatch, capsys
):
    # CRITICAL: cmd_state used to print run.released_rewards -- the state
    # machine's checkpoint bookkeeping, flipped regardless of operator
    # approval -- instead of the code_releases ledger. This is the
    # operator's ONLY visibility when the dashboard is down, so a wrong
    # answer here is the most costly place for one to appear.
    settings = _production_ready_settings()
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: sessionmaker)

    run = await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)

    # Simulate a checkpoint pass flipping the state machine's own bookkeeping
    # WITHOUT any code ever having been released -- the exact wrong-direction
    # case the reviewer reproduced ("says released=[1] before anything was
    # emitted").
    async with sessionmaker() as session:
        result = await session.execute(select(Run).where(Run.id == run.id))
        row = result.scalar_one()
        row.released_rewards = [1]
        await session.commit()

    await cli_module.cmd_state()
    out = capsys.readouterr().out
    assert "released=[]" in out
    assert "released=[1]" not in out


async def test_cmd_state_reflects_a_real_release(sessionmaker, account, monkeypatch, capsys):
    settings = _production_ready_settings()
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: sessionmaker)

    run = await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)
    await cli_module.cmd_release(run.id, 1, skip_confirmation=True)

    capsys.readouterr()
    await cli_module.cmd_state()
    out = capsys.readouterr().out
    assert "released=[1]" in out


async def test_cmd_release_reports_already_released_without_crashing(
    sessionmaker, account, monkeypatch, capsys
):
    settings = _production_ready_settings()
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: sessionmaker)

    run = await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)
    await cli_module.cmd_release(run.id, 1, skip_confirmation=True)
    capsys.readouterr()
    await cli_module.cmd_release(run.id, 1, skip_confirmation=True)
    assert "already released" in capsys.readouterr().out


async def test_cmd_release_prints_the_code_on_the_already_released_path(
    sessionmaker, account, monkeypatch, capsys
):
    # Ship-blocking finding (task-30 review, finding #5): a code emitted
    # once already but never actually reaching the operator (process died,
    # a copy failed) had no way to be recovered short of editing .env and
    # minting a brand new code -- exactly the scenario this fallback
    # module exists to avoid at midnight. AlreadyReleased used to print
    # only "was already released", never the code itself.
    settings = _production_ready_settings(reward_1_code="THE-REAL-CODE-0001")
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: sessionmaker)

    run = await RunRepository(sessionmaker).create(account.id, Difficulty.KIDDIE)
    await cli_module.cmd_release(run.id, 1, skip_confirmation=True)
    capsys.readouterr()

    await cli_module.cmd_release(run.id, 1, skip_confirmation=True)
    out = capsys.readouterr().out
    assert "already released" in out
    assert "THE-REAL-CODE-0001" in out


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
    #
    # `config/run.schema.json` lives at the repo root (alongside
    # config/run.example.yaml), not under server/ -- resolved relative to
    # this file rather than via a bare cwd-relative Path so this test is
    # correct whether pytest is invoked from server/ (as CI and this repo's
    # convention do) or from the repo root.
    import json

    committed = json.loads(
        (Path(__file__).parents[2] / "config" / "run.schema.json").read_text()
    )
    assert committed == RunConfig.model_json_schema()

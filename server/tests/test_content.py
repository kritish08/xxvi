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
    assert config.devil_lives == 3


def test_devil_lives_defaults_to_three_when_omitted(tmp_path):
    from xxvi.content.schema import RunConfig

    config = RunConfig.model_validate(
        {
            "recipient": "X",
            "acts": 1,
            "segments_per_act": 1,
            "questions": [{"prompt": "p", "accept": ["a"], "roast": "r"}],
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
    assert config.devil_lives == 3


def test_devil_lives_must_be_at_least_one(tmp_path):
    from xxvi.content.schema import RunConfig

    with pytest.raises(ValidationError, match="devil_lives"):
        RunConfig.model_validate(
            {
                "recipient": "X",
                "acts": 1,
                "segments_per_act": 1,
                "devil_lives": 0,
                "questions": [{"prompt": "p", "accept": ["a"], "roast": "r"}],
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


def test_question_count_must_match_total_segments(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "recipient: X\nacts: 2\nsegments_per_act: 4\n"
        "questions: []\ngames: []\ntrophies: []\nrewards: []\n"
        "copy: {coming_soon: a, teaser: b, how_to_play: c, closing: d}\n"
    )
    with pytest.raises(ValidationError, match="questions"):
        load_config(bad)


def test_accept_must_have_at_least_one_spelling(tmp_path):
    from xxvi.content.schema import Question

    with pytest.raises(ValidationError, match="accept"):
        Question(prompt="p", accept=[], roast="r")


# --- normalize_answer("") == normalize_answer("???") == "". An accept entry
# that normalises to empty would silently make submitting nothing the
# correct answer for that question -- a content-authoring typo that would
# only surface at midnight. Must fail loudly at load time instead.
def test_accept_entry_that_is_an_empty_string_is_rejected():
    from xxvi.content.schema import Question

    with pytest.raises(ValidationError, match="normalises to an empty string"):
        Question(prompt="Which console?", accept=["ps5", ""], roast="r")


def test_accept_entry_that_is_only_punctuation_is_rejected():
    from xxvi.content.schema import Question

    with pytest.raises(ValidationError, match="normalises to an empty string"):
        Question(prompt="Which console?", accept=["ps5", "???"], roast="r")


def test_accept_entry_that_is_only_whitespace_is_rejected():
    from xxvi.content.schema import Question

    with pytest.raises(ValidationError, match="normalises to an empty string"):
        Question(prompt="Which console?", accept=["ps5", "   "], roast="r")


def test_trophies_must_include_required_ids(tmp_path):
    bad = tmp_path / "bad.yaml"
    # Missing the "platinum" trophy
    bad.write_text(
        "recipient: X\nacts: 1\nsegments_per_act: 1\n"
        "questions:\n"
        "  - {prompt: 'p', accept: ['a'], roast: 'r'}\n"
        "games:\n"
        "  - {segment: 1, mechanic: simon, params: {}}\n"
        "trophies:\n"
        "  - {id: 'game-1', name: 'n', grade: bronze}\n"
        "  - {id: 'question-1', name: 'n', grade: bronze}\n"
        "  - {id: 'act-1', name: 'n', grade: gold}\n"
        "rewards:\n"
        "  - {id: 1, after_act: 1, label: 'r'}\n"
        "copy: {coming_soon: a, teaser: b, how_to_play: c, closing: d}\n"
    )
    with pytest.raises(ValidationError, match="platinum"):
        load_config(bad)


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


def test_rewards_must_cover_all_acts(tmp_path):
    bad = tmp_path / "bad.yaml"
    # Missing reward for act 2
    bad.write_text(
        "recipient: X\nacts: 2\nsegments_per_act: 1\n"
        "questions:\n"
        "  - {prompt: 'p1', accept: ['a'], roast: 'r'}\n"
        "  - {prompt: 'p2', accept: ['a'], roast: 'r'}\n"
        "games:\n"
        "  - {segment: 1, mechanic: simon, params: {}}\n"
        "  - {segment: 2, mechanic: update, params: {}}\n"
        "trophies:\n"
        "  - {id: 'game-1', name: 'n', grade: bronze}\n"
        "  - {id: 'game-2', name: 'n', grade: bronze}\n"
        "  - {id: 'question-1', name: 'n', grade: bronze}\n"
        "  - {id: 'question-2', name: 'n', grade: bronze}\n"
        "  - {id: 'act-1', name: 'n', grade: gold}\n"
        "  - {id: 'act-2', name: 'n', grade: gold}\n"
        "  - {id: 'platinum', name: 'n', grade: platinum}\n"
        "rewards:\n"
        "  - {id: 1, after_act: 1, label: 'r'}\n"
        "copy: {coming_soon: a, teaser: b, how_to_play: c, closing: d}\n"
    )
    with pytest.raises(ValidationError, match="rewards"):
        load_config(bad)


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


def test_get_config_loads_example_with_cache_clear(tmp_path, monkeypatch):
    # Drives resolution at a tmp_path this test fully controls, rather than
    # depending on whether the real (gitignored) config/run.yaml happens to
    # exist on whatever machine runs the suite -- see the sibling
    # `is_serving_example_content` tests below for the same isolation
    # pattern. `config_path` is absolute, so `_resolve_config_path` never
    # walks ancestors looking for a real repo `config/run.yaml`; the only
    # file it can possibly find is the `run.example.yaml` planted here.
    from xxvi.content.loader import get_config, resolved_config_path
    from xxvi.settings import Settings

    (tmp_path / "run.example.yaml").write_text(EXAMPLE.read_text())
    missing_run_yaml = tmp_path / "run.yaml"

    get_config.cache_clear()
    resolved_config_path.cache_clear()
    monkeypatch.setattr(
        "xxvi.content.loader.get_settings",
        lambda: Settings(config_path=str(missing_run_yaml)),
    )
    try:
        config = get_config()
        # The demo greets the player in the generic second person. It used
        # to be the literal "PLACEHOLDER", which became visible the moment
        # `recipient` started driving the profile tile.
        assert config.recipient == "you"
        assert config.total_segments == 8

        # Cache should be populated
        cache_info = get_config.cache_info()
        assert cache_info.hits > 0 or cache_info.misses > 0
    finally:
        # Clear for cleanup -- these lru_caches are keyed on nothing, so a
        # tmp-path-configured result left cached here would leak into every
        # later test in the session.
        get_config.cache_clear()
        resolved_config_path.cache_clear()


def test_get_config_from_server_cwd(monkeypatch):
    """Test that get_config works when CWD is server/ (the real usage pattern)."""
    from xxvi.content.loader import get_config, resolved_config_path

    # Clear cache first
    get_config.cache_clear()
    resolved_config_path.cache_clear()

    # Change to server directory (which is the parent of the test)
    monkeypatch.chdir(Path(__file__).parent.parent)

    try:
        config = get_config()
        assert config.total_segments == 8
        assert len(config.questions) == 8
    finally:
        get_config.cache_clear()
        resolved_config_path.cache_clear()


def test_is_serving_example_content_is_true_when_run_yaml_is_missing(tmp_path, monkeypatch):
    # The ship-blocking case: config/run.yaml was never hand-placed on the
    # box, so get_config() silently falls back to run.example.yaml -- the
    # player is asked "Q1 placeholder" and the run cannot be completed.
    # `is_serving_example_content()` is how a loud caller (cli check-config,
    # app startup) tells this apart from a real config being served.
    #
    # Driven at a tmp_path with no run.yaml, same isolation pattern as
    # `test_is_serving_example_content_is_false_for_a_real_config` below --
    # this must hold regardless of whether the real (gitignored)
    # config/run.yaml happens to exist on the machine running the suite.
    from xxvi.content.loader import get_config, is_serving_example_content, resolved_config_path
    from xxvi.settings import Settings

    (tmp_path / "run.example.yaml").write_text(EXAMPLE.read_text())
    missing_run_yaml = tmp_path / "run.yaml"

    get_config.cache_clear()
    resolved_config_path.cache_clear()
    monkeypatch.setattr(
        "xxvi.content.loader.get_settings",
        lambda: Settings(config_path=str(missing_run_yaml)),
    )
    try:
        assert is_serving_example_content() is True
    finally:
        get_config.cache_clear()
        resolved_config_path.cache_clear()


def test_is_serving_example_content_is_false_for_a_real_config(tmp_path, monkeypatch):
    from xxvi.content.loader import get_config, is_serving_example_content, resolved_config_path
    from xxvi.settings import Settings, get_settings

    real = tmp_path / "run.yaml"
    # Substitute the recipient FIELD, not a magic word in the file -- this
    # previously replaced the literal "PLACEHOLDER" and silently became a
    # no-op when the demo stopped using that string.
    real.write_text(
        EXAMPLE.read_text().replace('recipient: "you"', 'recipient: "Real Recipient"')
    )

    get_config.cache_clear()
    resolved_config_path.cache_clear()
    get_settings.cache_clear()
    monkeypatch.setattr(
        "xxvi.content.loader.get_settings", lambda: Settings(config_path=str(real))
    )
    try:
        assert is_serving_example_content() is False
        assert get_config().recipient == "Real Recipient"
    finally:
        get_config.cache_clear()
        resolved_config_path.cache_clear()
        get_settings.cache_clear()


def test_an_overlong_reward_label_is_rejected_at_load_not_at_midnight():
    # .reveal__title renders at up to 144px with no truncation -- this is the
    # one screen the whole run exists for, so a label that would overflow it
    # must fail when the config is loaded, not when the gift lands.
    from tests.factories import make_config

    with pytest.raises(ValidationError, match="label"):
        make_config(rewards=[{"id": 1, "after_act": 1, "label": "x" * 200}])


def test_identity_fields_default_so_an_existing_config_keeps_validating_unchanged():
    # config/run.yaml predates operator/title/strapline and must never be
    # touched by this change (it's gitignored, real, and private) -- so a
    # config that omits all three has to keep loading exactly as it did
    # before, with sensible generic defaults standing in.
    from tests.factories import make_config

    config = make_config()
    assert config.operator == "the operator"
    assert config.title == "XXVI"
    assert config.strapline == ""


def test_operator_is_bounded_for_display():
    # Same rationale as Reward.label (see that field's comment): a long
    # operator name would overflow whatever chrome renders it.
    from tests.factories import make_config

    with pytest.raises(ValidationError, match="operator"):
        make_config(operator="x" * 33)
    with pytest.raises(ValidationError, match="operator"):
        make_config(operator="")


def test_title_is_bounded_for_large_display_sizes():
    from tests.factories import make_config

    with pytest.raises(ValidationError, match="title"):
        make_config(title="x" * 17)
    with pytest.raises(ValidationError, match="title"):
        make_config(title="")


def test_strapline_is_bounded_and_optional():
    from tests.factories import make_config

    with pytest.raises(ValidationError, match="strapline"):
        make_config(strapline="x" * 65)
    # Empty is fine -- strapline is the one identity field allowed to be
    # unset entirely, since "render nothing rather than an empty element"
    # is a valid outcome for it client-side.
    assert make_config(strapline="").strapline == ""


def test_a_real_config_can_set_all_three_identity_fields():
    from tests.factories import make_config

    config = make_config(operator="Jordan", title="XXVI", strapline="years in the making.")
    assert config.operator == "Jordan"
    assert config.title == "XXVI"
    assert config.strapline == "years in the making."

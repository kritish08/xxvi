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

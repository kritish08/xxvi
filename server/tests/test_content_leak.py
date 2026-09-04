"""The answers must never be serialisable to the client.

`accept` (and `roast`) live only in the server's `Question`/`RunConfig`. A
player who opens DevTools, reads the network tab, or greps the JS bundle
must find no path to the answer. Two independent things keep that true
today:

1. `QuestionView` declares only `prompt` and `blank` -- `run_routes.py`
   builds it field by field, so a route that forgets to add a field simply
   doesn't leak it.
2. `QuestionView` uses Pydantic's default `extra="ignore"` config, with no
   `model_config` override in this file. That second half matters on its
   own: even a careless refactor to
   `QuestionView(**question.model_dump())` does NOT leak `accept`, because
   `extra="ignore"` silently drops any keys the model doesn't declare. The
   only way that construction *would* leak the answer is if `QuestionView`
   also picked up `model_config = ConfigDict(extra="allow")` -- at which
   point unpacking `**question.model_dump()` starts round-tripping `accept`
   straight into the serialised response. Neither half alone is the whole
   guarantee, so the tests below pin both: the declared-fields subset, the
   config staying closed to extras, and the dangerous construction path
   itself.
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


def test_the_question_view_cannot_be_loosened_to_accept_extra_fields():
    # Declaring only `prompt`/`blank` is worthless as a guard if the model
    # also allows arbitrary extra fields through -- `extra="allow"` would
    # let `accept` ride along on any `**dict` construction even though it
    # is not a declared field. This pins the config half of the guarantee,
    # not just the field-list half.
    extra_policy = run_routes.QuestionView.model_config.get("extra", "ignore")
    assert extra_policy != "allow", (
        "QuestionView permits extra fields (extra='allow'); this reopens "
        "the leak that 'only declaring prompt/blank' is supposed to close, "
        "since **question.model_dump() would then carry accept straight "
        "through to the client"
    )


def test_a_serialised_question_view_contains_no_accepted_answer():
    view = run_routes.QuestionView(prompt="Which game?", blank="___ __")
    assert "GTA" not in view.model_dump_json()


def test_unpacking_a_real_question_into_a_question_view_does_not_leak_the_answer():
    # Exercises the actual dangerous construction the module docstring
    # names: a future route built as `QuestionView(**question.model_dump())`
    # instead of field-by-field. With today's `extra="ignore"` config this
    # is safe -- `accept` and `roast` are silently dropped -- but only
    # because that config holds; test_the_question_view_cannot_be_loosened
    # is what keeps this test meaningful rather than accidentally green.
    question = Question(prompt="Which game?", accept=["GTA"], blank="___ __", roast="Nice try.")
    view = run_routes.QuestionView(**question.model_dump())
    assert "GTA" not in view.model_dump_json()

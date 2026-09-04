from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from xxvi.normalize import normalize_answer

# Every mechanic the client has a component registered for
# (web/src/games/registry.ts). A `Literal` on purpose: a typo in
# config/run.yaml is caught at content-load time rather than reaching the
# player as "unknown mechanic" on a screen he cannot get past.
Mechanic = Literal["simon", "update", "drift", "trophy_run", "stack"]
Grade = Literal["bronze", "silver", "gold", "platinum"]


class Question(BaseModel):
    prompt: str
    accept: list[str] = Field(min_length=1)
    blank: str = ""
    roast: str
    # Optional and off by default. Points are cosmetic: they are displayed,
    # never checked. Progression is trophies and segments, and `core/` never
    # learns this field exists.
    points: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def accept_entries_must_normalise_to_something(self) -> Self:
        # normalize_answer("") == normalize_answer("???") == "". An accept
        # entry that normalises to empty would make submitting *nothing* the
        # correct answer for this question -- a content-authoring typo (an
        # empty string, or a punctuation-only entry) that would only surface
        # at midnight, on a question nobody would think to re-check. Content
        # is hand-authored and loaded at startup, so this fails loudly on
        # load rather than degrading silently at answer-check time.
        for entry in self.accept:
            if normalize_answer(entry) == "":
                raise ValueError(
                    f"question {self.prompt!r}: accept entry {entry!r} "
                    "normalises to an empty string"
                )
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
    # No longer pinned to a `Literal` -- `VaultService._code_for` now
    # resolves any reward id through `Settings.reward_code`, which reads
    # `REWARD_{n}_CODE` from the environment for anything beyond the two
    # declared fields, so the vault can serve as many rewards as the config
    # declares acts. The bound that matters now is the configured act
    # count, enforced in `RunConfig.counts_line_up` (reward ids must fall
    # within `1..acts`, and be unique) rather than here on the field --
    # `counts_line_up` is where `acts` is actually known. The failure mode
    # this still prevents is unchanged: a mis-authored config/run.yaml used
    # to load cleanly and only fail at `submit_checkpoint` time with an
    # uncaught UnknownReward -- a 500 AFTER the state machine had already
    # advanced the run past the checkpoint (xxvi/api/run_service.py's
    # `submit_checkpoint`: `apply()` runs before `vault.release()`, and
    # nothing there catches UnknownReward). Failing loudly at content-load
    # time, well before midnight, is still the point.
    id: int = Field(ge=1)
    after_act: int = Field(ge=1)
    # Bounded because the reveal renders this at --type-display (up to 144px)
    # with no truncation and no ellipsis -- see web/src/shell/codereveal.css.
    # The limit is a rendering constraint, so it is enforced where a bad value
    # can still be fixed cheaply: config load, not the reveal itself.
    #
    # 32, not the 48 this started at. Measured in a real browser against the
    # actual `.reveal__title` rule rather than reasoned about: at a 1470px
    # viewport the shipped label ("₹1,000 PlayStation Network", 26 chars) wraps
    # to 3 lines, 36 chars to 4, and 48 to 5 -- and on a 390px phone a 48-char
    # label ran to fifteen. Three lines is what actually shipped and read well,
    # so the bound sits just above the label that proved it.
    label: str = Field(min_length=1, max_length=32)


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
    # Devil-mode life pool for the whole run. `core/` never reads config, so
    # this is threaded down into `machine.advance` as an explicit parameter
    # by whatever orchestration layer holds both the RunConfig and the
    # machine call -- never hardcoded in `core/`.
    devil_lives: int = Field(default=3, ge=1)
    # Wrong answers allowed per question before it counts as a segment
    # failure, in BOTH difficulties. Threaded into `RunService.submit_answer`
    # the same way `devil_lives` is threaded into `machine.advance` -- `core/`
    # never reads config. Floor of 1 means "one shot", the old behaviour;
    # nothing here can make a question unanswerable.
    question_attempts: int = Field(default=3, ge=1)

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

        # Rewards: each act must have exactly one reward
        reward_acts = {r.after_act for r in self.rewards}
        if reward_acts != set(range(1, self.acts + 1)):
            raise ValueError(
                f"rewards: must cover acts 1..{self.acts} exactly once, "
                f"got {sorted(reward_acts)}"
            )

        # Reward ids: the bound moved here from `Reward.id` (see that
        # field's comment) because `acts` -- the actual bound -- is only
        # known once the whole config is assembled. Out-of-range or
        # duplicate ids must fail here, at load time, rather than reaching
        # `VaultService._code_for` as an uncaught UnknownReward after the
        # checkpoint has already advanced the run past this reward.
        reward_ids = [r.id for r in self.rewards]
        out_of_range = sorted({i for i in reward_ids if i < 1 or i > self.acts})
        if out_of_range:
            raise ValueError(
                f"rewards: id must be within 1..{self.acts}, got {out_of_range}"
            )
        if len(set(reward_ids)) != len(reward_ids):
            duplicates = sorted({i for i in reward_ids if reward_ids.count(i) > 1})
            raise ValueError(f"rewards: id must be unique, duplicated {duplicates}")

        # Trophies: must include all required ids, extras allowed only if hidden
        required_ids = {
            f"game-{i}" for i in range(1, total + 1)
        } | {
            f"question-{i}" for i in range(1, total + 1)
        } | {
            f"act-{i}" for i in range(1, self.acts + 1)
        } | {
            "platinum"
        }

        trophy_ids = {t.id for t in self.trophies}
        missing_ids = required_ids - trophy_ids
        if missing_ids:
            raise ValueError(f"trophies: missing required ids {sorted(missing_ids)}")

        # Check for non-hidden extras (hidden trophies are allowed)
        extra_ids = trophy_ids - required_ids
        extra_non_hidden = [
            t.id for t in self.trophies if t.id in extra_ids and not t.hidden
        ]
        if extra_non_hidden:
            raise ValueError(
                f"trophies: unexpected non-hidden trophy ids {sorted(extra_non_hidden)}"
            )

        return self

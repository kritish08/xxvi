# XXVI — Open-Source Release

**Date:** 2026-09-04
**Status:** Approved, ready for implementation planning
**Predecessor:** `2026-08-07-xxvi-design.md` (the original build)

---

## 1. What changes and why

XXVI was built for one night, for one person. It ran, it worked, the codes
were redeemed. This spec covers turning that private artifact into a public
repository published as a project on **GeekOnPeak**, the author's technical
journal (see `geekonpeak.com/projects/marauders` for the house format:
architecture deep-dive, honest tradeoffs, MIT licence, GitHub linked).

**Audience, decided:** primarily *readers* — people who arrive from the
write-up to browse the architecture. Secondarily *runners* — the minority
who clone it should get a working game from one command, not a placeholder
screen. This ordering settles every tradeoff below: documentation and
honesty outrank onboarding polish, but "it doesn't actually boot" is not
acceptable.

**Non-goal:** a framework. Nobody is expected to author new game mechanics
or new reward backends against a stable plugin interface. The five mechanics
are the five mechanics.

### 1.1 What is already true (audited, not assumed)

These were verified before writing this spec and require no work:

- **Git history is clean.** `config/run.yaml` and `.env` were never
  committed. A sweep of all 118 commits for the real answers, the third-party
  names, and both account passwords returned zero hits. **No history rewrite
  is needed.** The only match, `2LV9-C7AZ-JPSK`, is a deliberately fake code
  hardcoded in `settings.py` as a blocklist entry.
- **Answers never reach the browser.** `accept` lives only in the server's
  `RunConfig`; submissions are checked server-side and the client is told
  only pass/fail. This is correct today but untested — see §4.
- **Pasted reward codes of any format already render safely.**
  `.reveal__code` has `word-break: break-word`, `max-width: 90vw`, and
  `user-select: all`.
- **`config/run.example.yaml` loads and validates.** It is stale — it
  predates the `stack` mechanic and the `lives` parameter — but it is not
  rejected. (An earlier draft of this spec claimed otherwise; that was
  wrong.)
- **Content is already config-driven.** Questions, trophy names, copy, and
  game layout all live in `config/run.yaml` and are validated by Pydantic at
  load time.

### 1.2 What is broken right now

- **One server test fails on every clone, forever.**
  `test_session_reports_the_countdown_before_go_live` asserts the run is not
  yet live; `GO_LIVE_ISO` was 2026-08-20 and that date has passed. The test
  depends on wall-clock time. Current state: 528 pass, 13 skip, 1 fail. The
  web suite is 173/173 green across 31 files.
- **Rewards are hardcoded to exactly two** — in the schema, not just the
  config. See §3.
- **The reward label can overflow the screen.** See §3.3.
- **Three Simon Says defects** in the post-mistake window. See §5.
- **No README, no LICENSE, no CI.**

---

## 2. Questions stay text-only

**Decided: no multiple-choice question type.**

An earlier draft proposed one. It was based on misreading a request; the game
has only ever had free-text questions with an `accept` list, and adding a
second question type would introduce a leak surface (options must be sent to
the client while the correct answer must not) to serve a mode nobody uses.

`Question` keeps its current shape. The one addition:

```yaml
questions:
  - prompt: "Which game did we fight over?"
    accept: ["GTA IV", "GTA 4"]
    blank: "___ __"
    roast: "..."
    points: 100        # OPTIONAL. Absent by default.
```

`points: int | None = None`. If **no** question in the file declares points,
the score UI does not appear anywhere — the field is inert and the game
behaves exactly as it does today.

**Points never gate anything.** Progression stays on trophies and segments.
The score is derived by a pure function over the answers already recorded and
displayed on the dossier and end screen. This is what keeps it cheap:
`core/machine.py` never learns points exist, there is no new column, and none
of the optimistic-concurrency care that touching `Run` would demand.

> **Open item for implementation:** confirm the recorded answer history
> carries enough to derive a score. If it does not, that is a migration —
> stop and raise it rather than adding one silently.

---

## 3. Any number of acts

Discovered while planning, after this spec's first draft: **rewards are not
the only thing pinned to two.** The checkpoint gates are too, and they are
the more dangerous of the pair.

### 3.0 Checkpoint gates

`GateId` is a `StrEnum` with fixed `CHECKPOINT_1` / `CHECKPOINT_2` members,
and `run_service.py` chooses between them twice (lines 195 and 393) with:

```python
gate = GateId.CHECKPOINT_1 if act == 1 else GateId.CHECKPOINT_2
```

With three acts, **act 3 silently accepts act 2's checkpoint code** — which
releases act 3's reward to someone who never cleared act 3. Unlike the reward
bug in §3.1, this one does not raise. It just quietly opens.

The fix is a computed `checkpoint_gate(act) -> f"checkpoint_{act}"`, which
reproduces the existing literals exactly. That matters: those strings are
already persisted in `gate_attempts.gate_id` for every run recorded, so the
generalisation must be format-preserving, not merely self-consistent.

`Settings.checkpoint_1_hash` / `checkpoint_2_hash` gain a
`checkpoint_hash(act)` accessor on the same pattern as reward codes: the two
declared fields keep serving acts 1 and 2 so no existing `.env` or test
changes, and `CHECKPOINT_{n}_HASH` is read from the environment beyond that.

**No migration is needed for any of this** — verified: `GateAttempt.gate_id`
is a plain `String(32)`, `CodeRelease.reward_id` is an untyped `Integer`, and
`Run.cleared_segments` is a JSON list.

### 3.1 The current limit

`acts` is already configurable to any number, but the reward path is pinned:

```python
# content/schema.py
id: Literal[1, 2]

# vault/service.py
if reward_id not in (1, 2):
    raise UnknownReward(...)
return {1: self._settings.reward_1_code, 2: self._settings.reward_2_code}[reward_id]
```

A three-act config **loads cleanly** and then raises `UnknownReward` at
checkpoint time — *after* `apply()` has already advanced the state machine
past the checkpoint. A 500 at the single moment the whole thing exists for.

### 3.2 Rewards

```yaml
acts: 3
rewards:
  - { id: 1, after_act: 1, label: "₹1,000 PlayStation Network" }
  - { id: 2, after_act: 2, label: "Steam Wallet — ₹500" }
  - { id: 3, after_act: 3, label: "dinner, my treat" }
```

- `Reward.id` drops `Literal[1, 2]` for a validator tying reward ids to the
  configured act count — the existing `counts_line_up` validator already
  checks that rewards cover acts exactly once, so this extends work that is
  already there.
- `VaultService._code_for` reads `REWARD_{n}_CODE` from the environment
  instead of two named `Settings` fields.
- `Settings.assert_production_ready` checks every configured reward's code
  against `_is_placeholder_reward`, not just codes 1 and 2.

**Every existing vault guarantee is preserved and must be re-proven by the
existing tests:** operator approval required; at-most-once per `(run, reward)`
enforced by the DB unique constraint, not application logic; the code value
never logged, never persisted, never in an exception message; a dry run
leaves the ledger untouched.

### 3.3 The label needs a real limit

`.reveal__title` renders at `--type-display`, which is
`clamp(4rem, 9vw, 9rem)` — up to 144px — with no `max-width` and no wrap
guard. The shipped label was 26 characters and broke at spaces. A longer one,
or a single long unbroken word, runs off screen.

Two-part fix, because either alone is insufficient:

1. **`max_length` on the Pydantic field**, so an over-long gift name is
   rejected at config-load time with a clear message — not at midnight, on
   the one screen that matters. Starting value **48 characters**.
2. **CSS hardening** on `.reveal__title`: `max-width` and an
   `overflow-wrap` guard for unbroken strings.

> The 48 is a starting number, not a measured one. **Verify it in a browser
> at phone and desktop widths before committing to it** and lower it if it
> does not hold. Do not assert this from arithmetic.

The code itself stays free-form: any format, any length, pasted as-is.

---

## 4. Making the config genuinely editable

The single highest-leverage item, and nearly free:

**Emit a JSON Schema from the Pydantic models.**
`RunConfig.model_json_schema()` → `config/run.schema.json`, referenced from
the top of the YAML:

```yaml
# yaml-language-server: $schema=./run.schema.json
```

VS Code then gives field autocomplete and inline errors *while typing*, with
no tooling to install. The validation already exists; this exposes it to the
editor.

Supporting pieces:

- **`python -m xxvi.cli validate-config <path>`** — human-readable errors for
  the terminal.
- **A CI job that validates the shipped example**, so it can never silently
  go stale again the way it did.
- **A leak test** pinning the property in §1.1: no question's `accept` values
  appear in any client-facing API response or in the built bundle. This joins
  the existing family — `test_docs_gating.py`, `build-leak.test.ts` — that
  already guards content leakage. The behaviour is correct today; the test
  stops it silently regressing.

### 4.1 A playable demo config

`config/run.example.yaml` stops being `"Q1 placeholder"` and becomes a real,
generic, complete run, so `docker compose up` on a fresh clone yields a
working game. `is_serving_example_content` already exists in the loader to
mark this state.

**Decided: the demo is generic, not PSN-framed.** The reward label becomes a
plain message rather than a gift card, so the template reads as a template.
The XXVI/PSN story is told in the README and the GeekOnPeak write-up, where
it belongs.

The demo must also carry the corrections the current example lacks: the
`stack` mechanic and `trophy_run`'s `lives` parameter.

---

## 5. The three Simon Says defects

All three live in the same place: `MISTAKE_HOLD_MS = 900`, the window after a
wrong press during which `SimonSays.tsx` sets a timeout to replay the
sequence. Throughout that window `phase` is still `"repeat"` and
`finished.current` is still `false`, so `press()` keeps accepting input.

1. **Extra presses burn extra tries.** A press inside the window appends to
   an `entered.current` that has not been cleared, compares against
   `sequence[position]` at a now-meaningless position, mismatches, and
   decrements `attemptsLeft` again. Two or three stray presses can drain the
   whole pool at once — and can drive `remaining <= 0`, firing
   `onFinish({passed: false})` while a timeout is still queued to call
   `setState` on a component that is going away.
2. **The header still reads "your turn"** during the window
   (`phase === "watch" ? "watch…" : "your turn"`), inviting input the game is
   about to discard.
3. **The success flash does not clear.** Reported from play. **Reproduce it
   with a failing test before fixing it** — the mechanism is not yet
   confirmed from reading the code, and a fix without a repro is a guess.

The fix for (1) and (2) is the same: an explicit locked state for the hold
window, rather than inferring input-acceptance from `phase`. The pending
timeout must also be cleared on unmount.

---

## 6. Repository surface

- **README.md** — what it is, why the architecture looks like it does, how to
  run it, and what someone should change to make it theirs. Screenshots. Links
  to the GeekOnPeak write-up. In the house voice: honest about tradeoffs and
  about what was cut.
- **LICENSE** — MIT, matching Marauders.
- **CI** — GitHub Actions running both suites (`pytest`, `vitest`) plus
  `validate-config` on the shipped example.
- **Asset provenance** — the four music tracks are the author's own
  Gemini-generated output and ship in the repo with a provenance note. Fonts
  (Archivo, IBM Plex) need their licences confirmed and recorded. Narration is
  OpenAI TTS output; note it and confirm redistribution terms.
- **`deploy/`** — currently hardcodes one specific host and domain,
  and a shared-Caddy tenancy arrangement specific to one server. Genericise
  it, keeping the *reasoning* (why it publishes no host ports, why it sits
  behind an existing proxy) because that reasoning is the interesting part
  for a reader.
- **`GO_LIVE_ISO`** — the failing test must not be fixed by moving the date
  forward, which only defers the failure. The test must construct its own
  time reference rather than depending on the wall clock.

---

## 7. Privacy — outside the code

`config/run.yaml` is gitignored and stays out of the repository. It contains
genuinely private material about the recipient and **names an identifiable
third party** in one question.

This constrains the write-up, not the code: **no screenshot in the GeekOnPeak
post may show a question screen with real content.** The demo config exists
partly so screenshots can be taken against it. Flagged here so it is not
rediscovered at publish time.

---

## 8. Out of scope

- A web-based config editor. The audience edits YAML in a PR; a CRUD UI would
  be the largest subsystem in the repo and carry its own auth surface.
- New game mechanics, or a plugin interface for them.
- Any change to the state machine, the concurrency model, or the persistence
  layer. If the points work in §2 turns out to need a migration, it stops and
  comes back for a decision.

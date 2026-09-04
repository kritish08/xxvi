"""Operational fallback. If the dashboard is broken, this still releases a
code.

    python -m xxvi.cli hash-secret               # checkpoint codes (free-form)
    python -m xxvi.cli hash-secret --activation   # the activation gate ONLY --
                                                   # see _normalize_activation_
                                                   # candidate's docstring for why
    python -m xxvi.cli check-config
    python -m xxvi.cli release --run 1 --reward 1
    python -m xxvi.cli release --run 1 --reward 1 --yes   # skip confirmation
    python -m xxvi.cli state
    python -m xxvi.cli validate-config [path]    # default: config/run.yaml
    python -m xxvi.cli emit-schema [out]         # default: config/run.schema.json

This module takes NO dependency on the HTTP layer, the realtime hub, or a
running server -- only `xxvi.settings`, the database (via
`xxvi.persistence`), and `xxvi.vault`. It exists specifically for the
moment the dashboard -- and everything built on top of FastAPI -- is
broken; if it imported any of that, the one thing it exists to survive
could take it down with it. Do not add an import of `xxvi.main`,
`xxvi.api`, `xxvi.realtime`, or `fastapi` to this file.
"""

import argparse
import asyncio
import getpass
import json
import re
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select

from xxvi.auth.passwords import hash_password
from xxvi.content.loader import get_config, is_serving_example_content
from xxvi.content.schema import RunConfig
from xxvi.persistence.models import Run
from xxvi.persistence.session import get_sessionmaker
from xxvi.settings import ConfigNotProductionReady, get_settings
from xxvi.vault.service import AlreadyReleased, VaultService

_PLACEHOLDER_RECIPIENT = "PLACEHOLDER"

# server/xxvi/cli.py -> server/xxvi -> server -> repo root. config/ lives at
# the repo root (alongside config/run.yaml, which is gitignored), not under
# server/ -- resolved from this file rather than from cwd so both
# subcommands below behave the same whether invoked from the repo root or
# from server/ (the latter is how CI and this repo's tooling run things).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SCHEMA_PATH = _REPO_ROOT / "config" / "run.schema.json"


def _looks_like_placeholder_text(text: str) -> bool:
    """Catches hand-authored content that still reads as placeholder copy
    (e.g. run.example.yaml's "Q1 placeholder") without requiring an exact
    string match -- a content author could reasonably leave the word in a
    slightly different shape and this must still catch it."""
    return "placeholder" in text.lower()


def _content_placeholder_offenders(config: RunConfig) -> list[str]:
    """Content-level placeholder tells, checked in addition to (not instead
    of) `is_serving_example_content()` -- a hand-edited `config/run.yaml`
    that still has placeholder copy in it (recipient never filled in, a
    question prompt left unwritten) is exactly as unplayable at midnight as
    the file being missing outright, and would otherwise sail through this
    check because a *file* does exist at the real path."""
    offenders: list[str] = []
    if config.recipient == _PLACEHOLDER_RECIPIENT:
        offenders.append(
            f"recipient is still the placeholder value {_PLACEHOLDER_RECIPIENT!r}"
        )
    for i, question in enumerate(config.questions, start=1):
        if _looks_like_placeholder_text(question.prompt):
            offenders.append(
                f"question {i} prompt still looks like placeholder text: {question.prompt!r}"
            )
    return offenders


def _normalize_activation_candidate(raw: str) -> str | None:
    """Mirror web/src/shell/Activation.tsx's `formatKey` EXACTLY: uppercase,
    strip every character that isn't A-Z0-9, then re-group into
    `XXXX-XXXX-XXXX`. That dashed string -- not the bare 12 characters --
    is what the client actually POSTs, and `gates/service.py`'s
    `candidate.strip().upper()` does not strip dashes. So the activation
    gate's hash must be of the dashed form, or activation never passes.

    Returns `None` (a refusal, not a silent best-effort) if fewer or more
    than exactly 12 alphanumeric characters survive cleaning -- that is
    the one shape `Activation.tsx`'s submit button will ever let through
    (`KEY_PATTERN`), so anything else is a hash the real client could
    never reproduce and must not be minted.
    """
    cleaned = re.sub(r"[^A-Z0-9]", "", raw.strip().upper())
    if len(cleaned) != 12:
        return None
    return "-".join(cleaned[i : i + 4] for i in range(0, 12, 4))


def cmd_hash_secret(*, activation: bool = False) -> None:
    if activation:
        # The activation gate is the one gate whose client formats and
        # dashes the value before sending it (see Activation.tsx) -- every
        # other gate (checkpoints) is free-form and the plain path below is
        # still correct for those.
        plain = getpass.getpass(
            "activation riddle answer (exactly 12 letters/digits -- dashes, "
            "spaces, and case are ignored and normalised for you): "
        )
        normalized = _normalize_activation_candidate(plain)
        if normalized is None:
            print(
                "refused: after removing everything but letters and digits "
                "and uppercasing, that answer is not exactly 12 characters "
                "long -- the real client can never produce that shape, so "
                "hashing it would mint a code that can never verify. "
                "Recheck the riddle answer."
            )
            raise SystemExit(1)
        # Show the operator the literal string being hashed -- the exact
        # value the real client will send, dashes included, so there is no
        # ambiguity about what this hash actually gates.
        print(f"hashing the literal string the client will send: {normalized}")
        print(hash_password(normalized))
        return

    plain = getpass.getpass("secret (will be uppercased and stripped): ")
    print(hash_password(plain.strip().upper()))


def cmd_check_config() -> None:
    """Preflight: run this ahead of the event, not just at midnight.

    This used to check `Settings` only -- it never loaded the run content
    at all. A missing `config/run.yaml` (it's gitignored and
    volume-mounted, never baked into the image) made `get_config()`
    silently fall back to `run.example.yaml`: every preflight, including
    this one, stayed green while the real run would ask "Q1 placeholder"
    and expect "placeholder1". This now loads content and fails loudly on
    exactly that, plus on placeholder copy left in an otherwise-real file.
    """
    try:
        get_settings().assert_production_ready()
    except ConfigNotProductionReady as exc:
        print(f"NOT ready: {exc}")
        raise SystemExit(1) from None

    if is_serving_example_content():
        print(
            "NOT ready: config/run.yaml was not found -- serving "
            "run.example.yaml placeholder content instead. Place the real "
            "config/run.yaml on this box before go-live and re-run this "
            "command."
        )
        raise SystemExit(1)

    offenders = _content_placeholder_offenders(get_config())
    if offenders:
        print("NOT ready: " + "; ".join(offenders))
        raise SystemExit(1)

    print("config OK")


async def cmd_release(run_id: int, reward_id: int, *, skip_confirmation: bool) -> None:
    settings = get_settings()
    # Refuse to release a dummy/placeholder code. This is the one path this
    # module exists to protect -- see assert_production_ready's docstring.
    settings.assert_production_ready()

    if not skip_confirmation:
        answer = input(
            f"Release reward {reward_id} for run {run_id}? This emits a real "
            f"gift-card code and cannot be undone. Type 'yes' to continue: "
        )
        if answer.strip().lower() != "yes":
            print("aborted, nothing released")
            return

    # Invoking this command with explicit --run/--reward, past the
    # confirmation prompt above, IS the operator's approval -- there is no
    # further approval step for this fallback path to defer to.
    vault = VaultService(get_sessionmaker(), settings)
    try:
        code = await vault.release(run_id, reward_id, approved_by_operator=True)
    except AlreadyReleased:
        # This IS the operator's recovery path when a code was emitted once
        # already but never actually reached him (the release happened, the
        # process died before this printed, a copy failed silently) -- see
        # VaultService.code_for's docstring. Printing nothing here, as this
        # used to, left the operator with no way to recover an emitted code
        # short of editing .env and minting a NEW one, which is exactly the
        # scenario this fallback module exists to avoid at midnight.
        print(
            f"reward {reward_id} was already released for run {run_id} "
            f"-- code: {vault.code_for(reward_id)}"
        )
        return
    print(code)


async def cmd_state() -> None:
    """The operator's ONLY visibility when the dashboard is broken -- this
    must read the same source of truth the dashboard does.

    `Run.released_rewards` is the state machine's own bookkeeping, written
    at checkpoint pass regardless of operator approval -- it flips before
    any code has actually been emitted, and never un-flips after a real
    release either. Reading it here would print "released" before a
    release happened and keep printing it (unchanged) after one did,
    making this command actively misleading at the one moment it exists to
    be trusted. `code_releases` (via `VaultService.released_reward_ids`) is
    the actual ledger of codes emitted -- this mirrors
    `operator_routes.operator_state`, which was already fixed to read it.
    """
    sessionmaker = get_sessionmaker()
    vault = VaultService(sessionmaker, get_settings())
    async with sessionmaker() as session:
        runs = (await session.execute(select(Run))).scalars().all()
    for run in runs:
        released = sorted(await vault.released_reward_ids(run.id))
        print(f"run={run.id} phase={run.phase} segment={run.segment} "
              f"difficulty={run.difficulty} released={released}")


def cmd_validate_config(path: str) -> int:
    """Validate a run config file and report readable errors.

    A raw pydantic traceback is not something a stranger editing YAML for
    the first time can act on, so every error is printed as one line:
    `<dotted.field.path>: <message>`. The path is resolved the same way
    `xxvi.content.loader` resolves `config/run.yaml` -- so the bare string
    "config/run.yaml" (or "config/run.example.yaml") works whether this is
    invoked from the repo root or from server/ -- but `example_fallback` is
    off: this command validates exactly the file it was asked to, it never
    silently substitutes run.example.yaml the way app startup does.
    """
    from xxvi.content.loader import _resolve_config_path, load_config

    try:
        resolved = _resolve_config_path(path, example_fallback=False)
    except FileNotFoundError as exc:
        print(f"error: {exc}")
        return 1

    try:
        load_config(resolved)
    except ValidationError as exc:
        for error in exc.errors():
            dotted = ".".join(str(part) for part in error["loc"])
            print(f"{dotted}: {error['msg']}")
        return 1

    print(f"{resolved}: OK")
    return 0


def cmd_emit_schema(out: str = str(_DEFAULT_SCHEMA_PATH)) -> int:
    """Write `RunConfig`'s JSON Schema to `out`.

    Generated, not hand-maintained, so it can never say something the
    model does not -- `test_the_committed_schema_is_in_sync_with_the_model`
    (tests/test_cli.py) fails CI if this ever falls behind a model change.
    Referenced from config/run.example.yaml via a
    `# yaml-language-server: $schema=./run.schema.json` comment, which is
    why the default output path sits next to it at the repo root.
    """
    schema = RunConfig.model_json_schema()
    Path(out).write_text(json.dumps(schema, indent=2) + "\n")
    print(f"wrote {out}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="xxvi")
    sub = parser.add_subparsers(dest="command", required=True)
    hash_secret = sub.add_parser("hash-secret")
    hash_secret.add_argument(
        "--activation",
        action="store_true",
        help=(
            "hash an activation-gate riddle answer with the client's exact "
            "XXXX-XXXX-XXXX normalisation (see cmd_hash_secret's docstring) "
            "instead of the generic strip+uppercase used for checkpoint codes"
        ),
    )
    sub.add_parser("check-config")
    release = sub.add_parser("release")
    release.add_argument("--run", type=int, required=True)
    release.add_argument("--reward", type=int, required=True)
    release.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt"
    )
    sub.add_parser("state")
    validate_config = sub.add_parser("validate-config")
    validate_config.add_argument("path", nargs="?", default="config/run.yaml")
    emit_schema = sub.add_parser("emit-schema")
    emit_schema.add_argument("out", nargs="?", default=str(_DEFAULT_SCHEMA_PATH))

    args = parser.parse_args()
    match args.command:
        case "hash-secret":
            cmd_hash_secret(activation=args.activation)
        case "check-config":
            cmd_check_config()
        case "release":
            asyncio.run(cmd_release(args.run, args.reward, skip_confirmation=args.yes))
        case "state":
            asyncio.run(cmd_state())
        case "validate-config":
            raise SystemExit(cmd_validate_config(args.path))
        case "emit-schema":
            raise SystemExit(cmd_emit_schema(args.out))


if __name__ == "__main__":
    main()

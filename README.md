# XXVI

XXVI is a desktop web experience disguised as a PlayStation console, built
as a birthday gift for one person: he boots what looks like a PS console,
finds a library holding one game he's never seen, sitting at 0%, and clears
it to reach a Platinum trophy. It ran once, live, at midnight, for a real
person, and the gift it unlocked was real. This repository is that system,
generalised so someone else can point it at their own person, their own
questions, and their own gift.

Clearing the game means clearing 8 segments, each a minigame followed by a
question only the intended recipient could answer. Clearing an "act" (a
group of segments) makes the operator — the gift-giver, watching from a
second screen — release a real gift-card code. Two difficulty modes:
KIDDIE (a fail costs only the current segment) and DEVIL (three lives for
the whole run). Five minigame mechanics: `simon`, `stack`, `drift`,
`trophy_run`, `update`.

## Quickstart: play the demo

No editing of game content is required to try this — `config/run.yaml`
(the real, personal content) is gitignored and never shipped; if it's
absent the server automatically serves `config/run.example.yaml`, a
genuinely playable two-act demo, and says so loudly in its logs. You do
need to fill in a handful of secrets in `.env`, since nothing sensitive
ships pre-filled:

```bash
git clone <this-repo-url>
cd birthday-fun
cp .env.example .env
```

Generate a session secret and a demo login (this uses the `api` image's
own CLI, so no local Python install is needed):

```bash
docker compose build api
openssl rand -hex 32                                    # -> SESSION_SECRET
echo 'demo-password' | docker compose run --rm api python -m xxvi.cli hash-secret
                                                          # -> PLAYER_PASSWORD_HASH
echo 'demo-password' | docker compose run --rm api python -m xxvi.cli hash-secret
                                                          # -> OPERATOR_PASSWORD_HASH
```

Paste those into `.env` (`SESSION_SECRET`, `PLAYER_USERNAME`,
`PLAYER_PASSWORD_HASH`, `OPERATOR_USERNAME`, `OPERATOR_PASSWORD_HASH`), set
`SITE_DOMAIN=localhost`, then bring the stack up:

```bash
docker compose up -d --build
```

Visit `https://localhost` and log in as the player account to play the
demo; the operator dashboard lives behind the operator account on the same
host. Caddy's internal CA issues a certificate for `localhost` automatically
in this mode — browsers will flag it as untrusted, which is expected for a
local run (see the comment at the top of `Caddyfile`).

`.env.example`'s default `GO_LIVE_ISO` is already in the past, so the demo
run is live immediately — no waiting on a countdown.

*This sequence is written from reading the compose/Dockerfiles rather than
from a fresh-clone run in this session — if a step is off, the compose
files and `docs/runbook.md` are the source of truth to reconcile against.*

## Make it yours

1. Copy `config/run.example.yaml` to `config/run.yaml` and edit it. It's
   gitignored on purpose — this is where the real, personal content goes,
   and it never gets committed. `config/run.schema.json` is generated from
   the same Pydantic models the server validates against
   (`server/xxvi/content/schema.py`), so pointing an editor at it (VS Code
   picks it up automatically via the schema association) gets you
   autocomplete and inline errors while you write. From the terminal:

   ```bash
   cd server && .venv/bin/python -m xxvi.cli validate-config ../config/run.yaml
   ```

2. Any number of acts is supported — checkpoint gates and reward releases
   both used to be hardcoded to exactly two; a third act used to load
   without error and then either release the wrong reward or 500 at the
   checkpoint. Gate ids are now computed (`checkpoint_gate(act)`), and
   secrets follow an `{n}` convention: `REWARD_{n}_CODE` for the gift-card
   codes, `CHECKPOINT_{n}_HASH` for the checkpoint answer hashes (act 1
   and 2 keep their original env var names for backward compatibility; act
   3 onward reads `REWARD_3_CODE` / `CHECKPOINT_3_HASH` directly). See the
   comments in `.env.example` for the exact shape, including a documented
   trap: the activation code hash must be generated from the *dashed*
   `XXXX-XXXX-XXXX` form the client actually sends, not the bare answer.

3. Set real values in `.env` — `REWARD_{n}_CODE`, `CHECKPOINT_{n}_HASH`,
   credentials — and confirm you're actually ready before an event:

   ```bash
   cd server && .venv/bin/python -m xxvi.cli check-config
   ```

   This must print `config OK`. If it reports placeholder content or a
   missing reward/checkpoint value, fix that before going live — there is
   no recovery path for realizing this at midnight.

## Architecture, and why

- **Server-authoritative game verification** (`server/xxvi/games/verify.py`).
  The client reports `passed_client_side` after a minigame, but that field
  is advisory and structurally ignored — the server independently
  re-derives the verdict from the segment's seed, the claimed input count,
  and a wall-clock check against the segment token's own signed issue
  time, so a claimed `duration_ms` can never exceed how much real time has
  actually passed since the token was handed out. `drift` (continuous
  steering, not discrete answers) is deliberately exempt from the
  per-input rate floor that the other mechanics use — applying it there
  penalized playing *well*, not playing dishonestly.

- **Optimistic concurrency** on `Run.version` — every mutation is a
  compare-and-swap against the version the caller last read, not a lock.
  Deletes are ordered explicitly by foreign key rather than relying on
  `ON DELETE CASCADE`, since this schema doesn't use it.

- **Insert-first-catch-unique-violation** as the at-most-once idiom for
  `code_releases`, `consumed_tokens`, and `trophies_earned`
  (`server/xxvi/vault/service.py`). Rather than checking-then-inserting
  (a race), the code inserts and treats a unique-constraint violation on
  `(run_id, reward_id)` as "already done." `_is_unique_violation`'s
  docstring is worth reading directly — it explains why a bare
  `except IntegrityError` here would be catastrophic (it would silently
  swallow a *foreign-key* violation too, e.g. an invalid run id, as a
  quiet false "already released," and emit no code at all with no error).

- **Vault invariants**, held nowhere else: a code is emitted only with
  explicit operator approval; at most once per `(run, reward)`, enforced
  by a database `UNIQUE` constraint rather than application logic; the
  code value is never logged, never persisted outside the moment of
  release, and never appears in an exception; and a dry run leaves no
  ledger trace at all.

- **A three-bus WebAudio mix** — MUSIC, SFX, VOICE — with crossfaded music
  loops, a `DynamicsCompressorNode` acting as a safety limiter rather than
  a shaping tool, and bus-level ducking (VOICE ducks MUSIC/SFX; a trophy
  sting ducks MUSIC) (`web/src/lib/audio.ts`).

- **Pydantic → OpenAPI → generated TypeScript client.** `npm run codegen`
  emits the server's OpenAPI schema without a running server and feeds it
  through `openapi-typescript`, so the frontend's request/response types
  come from the same Pydantic models the API actually validates against.

## What was cut, and what's still imperfect

- **A web-based config editor was cut on purpose.** The audience is
  expected to edit `config/run.yaml` in a PR; a CRUD UI for it would be
  the largest subsystem in this repo and would carry its own auth surface
  for very little gained.
- **New game mechanics, or a plugin interface for adding one, are out of
  scope.** The five mechanics shipped are the five the original run used.
- **`force-golive` is in-memory only**, not persisted to the database — a
  restart after forcing go-live resets it, and the operator has to notice
  `GET /api/session` reporting `live: false` again and re-force it. This
  is a known, accepted limitation, documented loudly in `docs/runbook.md`
  rather than fixed, since adding a migration for a once-only live event
  felt like the wrong tradeoff this close to shipping.
- **One of three Simon Says defects reported from play could not be
  reproduced from reading the code**, and per this project's own rule for
  claims like that, it was left unfixed rather than "fixed" without a
  repro: a success flash that reportedly doesn't clear, in the ~900ms hold
  window after a wrong press. The other two defects in that same window
  (extra presses during the hold window burning extra tries; the header
  still inviting input the game is about to discard) were confirmed by
  reading the code and fixed. If you can reproduce the third one, a
  failing test is the way in.
- **Narration is generated but disabled** (see
  `web/public/audio/PROVENANCE.md`) — two full TTS generation passes were
  produced and both were judged wrong for the console this is trying to
  be, not just for voice quality. Every narrated line has an on-screen
  text equivalent, so nothing is functionally lost with it off.
- Screenshots below were taken against `config/run.example.yaml`, the
  shipped demo config — never against real content. No screenshot in this
  repo or in the linked write-up shows a real question or a real answer.

## Screenshots

*Pending — none are included in this initial release. When added, they
will be taken against the demo config only (see above), not real content.*

## Write-up

A longer write-up of how this was built lives at
[geekonpeak.com](https://geekonpeak.com).

## Licence

MIT. See `LICENSE`. Copyright (c) 2026 Kritish.

The four music tracks under `web/public/audio/music/` are the author's own
Gemini-generated output, redistributed under this same licence. See
`web/public/audio/PROVENANCE.md` for the full provenance of the audio
assets, including the narration files (currently unused — see above).

Fonts (Archivo, IBM Plex Sans, IBM Plex Mono) are licensed under the SIL
Open Font License, Version 1.1 — confirmed against
[IBM/plex's `LICENSE.txt`](https://github.com/IBM/plex/blob/master/LICENSE.txt)
and [google/fonts' `ofl/archivo/OFL.txt`](https://github.com/google/fonts/blob/main/ofl/archivo/OFL.txt).

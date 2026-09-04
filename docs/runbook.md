# XXVI — night-of runbook

Read this at midnight, on a call, possibly panicking. It is written for
that moment, not for a calm afternoon of documentation reading.

## Non-negotiable, read this first

**The gift-card codes live in my notes.** If anything breaks — server down,
Docker won't start, the whole stack on fire — paste the codes into
WhatsApp. It becomes a funny story, not a crisis.

**The gift is guaranteed. The experience is what's allowed to fail.**
Nothing below is worth panicking over. If a fix doesn't land in a couple of
minutes, stop debugging and send the codes.

---

## Several days before — dress rehearsal (not optional)

Run the whole thing on the actual laptop you'll use on the night, with
dummy codes, screen-sharing to Discord, in fullscreen.

- [ ] Full run start to finish, both difficulties (KIDDIE and DEVIL)
- [ ] **Discord: share the ENTIRE SCREEN, not the browser window or a
      single app.** Fullscreen can black out a window-capture share,
      badly, on macOS — you will not notice this is happening on your end;
      the other side just sees black. Screen share, not window share.
- [ ] Trophy pops are legible through Discord's video compression at the
      resolution/bitrate you'll actually be sharing at
- [ ] **Trophy pops read as complete with the sound muted.** A screen
      share may not carry system audio at all, or the viewer may have
      their volume down — the visual alone must land the moment.
- [ ] Operator dashboard updates live while he plays (events, trophies,
      gate attempts all show up without a manual refresh)
- [ ] A toast sent from the operator dashboard lands on his screen
      mid-game
- [ ] Force go-live works (`POST /api/operator/force-golive`) — confirm
      `GET /api/session` flips `live` to `true` immediately
- [ ] Clear-lockout works after three wrong checkpoint codes
      (`POST /api/operator/unlock-gate {run_id, gate: "checkpoint_1"}` or
      `"checkpoint_2"`)
- [ ] `python -m xxvi.cli release --run <N> --reward 1` works with the
      operator dashboard closed — this is the fallback path, prove it
      works standalone

If any of these fail during the rehearsal, there are still days to fix it.
That is the entire point of doing this early.

---

## Before the 20th — one-time housekeeping

- [ ] **Place the real `config/run.yaml` on this box.** It's gitignored
      and volume-mounted (never baked into the image) specifically so the
      real content never touches the repo — but that also means nothing
      puts it there for you. If it's missing, the app silently serves
      `config/run.example.yaml` instead: the player is asked "Q1
      placeholder" and the run cannot be completed. `GET /api/health`
      stays green through this; it does not check content. Prove the real
      file is in place with:
      ```bash
      cd server && .venv/bin/python -m xxvi.cli check-config
      ```
      This must print `config OK`. If it prints `NOT ready: config/run.yaml
      was not found...`, the file isn't there yet — fix that before
      anything else on this list.
- [ ] **Rotate the Neon password.** The current one (Neon project "xxvi",
      branch main) has appeared in a development transcript and must be
      treated as burned. Rotate it in the Neon console, update
      `DATABASE_URL` in `.env` with the new password, and re-run the
      migration step below against the new credential before moving on.
- [ ] Add `SITE_DOMAIN=<your real domain>` to `.env` — the `caddy` service
      reads it via `env_file` to fill in the Caddyfile's `{$SITE_DOMAIN}`
      and to request its TLS certificate. DNS for that domain must already
      point at this machine's public IP.
- [ ] Run migrations once, against Neon's **direct** endpoint (never the
      `-pooler` one — the pooler can reject the session-level DDL a
      migration needs, and this must not be discovered live):
      ```bash
      docker compose run --rm api alembic upgrade head
      ```
      This reuses the api image (already built) and `.env`'s
      `DATABASE_URL`, without starting the long-running service.

---

## On the 20th, before midnight IST

Work through this in order. Each step should take under a minute; if one
doesn't, move to the next non-negotiable action (WhatsApp the codes) rather
than debugging under pressure.

1. [ ] **Put the REAL gift-card codes and secrets into `.env`** —
       `REWARD_1_CODE`, `REWARD_2_CODE`, `CHECKPOINT_1_HASH`, and
       `CHECKPOINT_2_HASH` (generate each hash with `cd server &&
       .venv/bin/python -m xxvi.cli hash-secret`).
       **`ACTIVATION_CODE_HASH` is different** — it must be generated with
       `.venv/bin/python -m xxvi.cli hash-secret --activation`, not the
       plain command above. The web client always sends the riddle answer
       as a dashed `XXXX-XXXX-XXXX` (12 letters/digits), and the server
       does not strip dashes — hashing the bare answer mints a code that
       can never verify, and there is no operator bypass for activation
       (see `.env.example` for the full explanation). The `--activation`
       mode prints the literal dashed string it hashed; double-check it
       reads as the riddle answer you intended before moving on.
       Confirm `GO_LIVE_ISO` is still the real midnight and
       `DRY_RUN=false`. Confirm `config/run.yaml` is still in place (see
       "Before the 20th" above) and re-run
       `.venv/bin/python -m xxvi.cli check-config` — it must print
       `config OK`, not just the settings half of preflight.
2. [ ] Bring the stack up:
       ```bash
       docker compose up -d --build
       ```
3. [ ] Confirm the API is alive:
       ```bash
       curl -sf https://$SITE_DOMAIN/api/health
       ```
       Expect `{"status":"ok"}`. If TLS isn't ready yet (fresh cert), retry
       once or twice a few seconds apart before treating it as a real
       problem.
4. [ ] Confirm the countdown reports sanely (not live yet, a believable
       number of seconds until midnight):
       ```bash
       curl -s https://$SITE_DOMAIN/api/session
       ```
       Expect `"live": false` and `"seconds_until_live"` roughly matching
       how long is actually left.
5. [ ] **Reset his run** so he starts clean (this deletes his run and its
       events/trophies/gate-attempts, not his account — he keeps his
       login). There is no `ON DELETE CASCADE` in this schema, so a bare
       `DELETE FROM runs ...` will fail on a foreign-key violation; use
       this instead:
       ```bash
       cd server && .venv/bin/python - <<'PY'
       import asyncio
       from sqlalchemy import text
       from xxvi.persistence.session import get_engine

       USERNAME = "REPLACE_WITH_PLAYER_USERNAME"  # PLAYER_USERNAME in .env

       async def reset():
           async with get_engine().begin() as conn:
               run_id = (await conn.execute(
                   text("SELECT r.id FROM runs r JOIN accounts a ON a.id = r.account_id "
                        "WHERE a.username = :u"),
                   {"u": USERNAME},
               )).scalar_one_or_none()
               if run_id is None:
                   print("no run found for", USERNAME, "-- nothing to reset")
                   return
               for table in ("consumed_tokens", "code_releases", "gate_attempts",
                             "trophies_earned", "run_events"):
                   await conn.execute(text(f"DELETE FROM {table} WHERE run_id = :rid"),
                                       {"rid": run_id})
               await conn.execute(text("DELETE FROM runs WHERE id = :rid"), {"rid": run_id})
           print("reset run", run_id, "for", USERNAME)

       asyncio.run(reset())
       PY
       ```
6. [ ] Send the riddle email carrying `ACTIVATION_CODE` (the plaintext
       code you hashed into `ACTIVATION_CODE_HASH` in step 1 — write it
       down before you hash it, hashes don't invert).
7. [ ] Open the operator dashboard and confirm his profile flips to online
       once he logs in.

---

## If it goes wrong

| Symptom | Do this |
|---|---|
| Gate didn't open at midnight | Force go-live on the operator dashboard (or `POST /api/operator/force-golive`) |
| He's locked out of a checkpoint (3 wrong codes) | Clear the gate on the dashboard (or `POST /api/operator/unlock-gate {run_id, gate: "checkpoint_1"}` / `"checkpoint_2"`) |
| Dashboard is broken but the server is up | `cd server && .venv/bin/python -m xxvi.cli release --run <N> --reward <M>` — this is the dashboard-independent release path, built for exactly this |
| Server is down / Docker won't come up / anything else | **WhatsApp the codes. Laugh about it.** See "Non-negotiable" above — this is always an acceptable outcome. |

---

## Known limitation: force go-live does not survive a restart

`POST /api/operator/force-golive` sets an in-memory flag
(`app.state.force_unlocked`) — it is not written to the database. If the
container restarts or is redeployed (`docker compose up -d --build`,
a crash, an OOM kill) **after** you forced go-live, the flag resets to
`false` and the gate re-locks until either `GO_LIVE_ISO` actually passes
or you force go-live again.

This matters most in exactly the scenario force-golive exists for: you
already forced it open early (the real midnight isn't cooperating,
his clock is off, whatever), then something else forces a restart —
and the gate quietly re-locks with no alarm, no log line, nothing on the
dashboard calling it out.

**Do this:** if the stack restarts for any reason after you've forced
go-live, immediately re-check `GET /api/session` (`"live"` should be
`true`) and re-force go-live if it isn't. Avoid restarting the stack at
all once you've forced go-live unless something is actually broken.

---

## Quick reference

```bash
# Bring the stack up (after building images at least once)
docker compose up -d

# Tail logs if something looks wrong
docker compose logs -f api

# One-off migration run (direct Neon endpoint, from .env)
docker compose run --rm api alembic upgrade head

# Dashboard-independent release fallback
cd server && .venv/bin/python -m xxvi.cli release --run <N> --reward <M>

# Check current state without the dashboard
cd server && .venv/bin/python -m xxvi.cli state
```


## First start on an empty database

The api runs `seed_accounts` during startup, which needs the tables to
already exist — so on a brand-new volume it exits with
`relation "accounts" does not exist` and compose reports it unhealthy.
Migrate first, from a throwaway container that does not wait on the api:

```bash
docker compose up -d db
docker compose run --rm --no-deps api sh -c "cd /app && python -m alembic upgrade head"
docker compose up -d
```

Thereafter `docker compose up -d --build` is enough.

`--env-file /dev/null` silences ~80 warnings about `$` in `.env` (every
argon2 hash contains `$argon2id$v=19$m=...` and compose tries to interpolate
them). The api reads `.env` itself from a mount, so this changes nothing
about what it sees.

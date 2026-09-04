# XXVI — Design

**Date:** 2026-08-07 (revised 2026-08-08)
**Status:** Approved, ready for implementation planning
**Go-live:** **20 Aug 2026, 00:00 IST.** Fixed. **12 days from revision.**

---

## 1. What this is

A **desktop web experience**, disguised as a game console, built for one specific person: my best friend of twenty years, turning 26.

He boots what looks like a PS console. His library holds exactly one game he's never seen — **`XXVI`**, sitting at 0%. To reach the Platinum he must clear eight segments, each one a minigame followed by a question only he could answer. Clearing an act releases a real PlayStation Network gift card code.

### 1.0 The title

**`XXVI`** — never explained anywhere in the product.

GTA numbers its entries in roman numerals, so the title reads as a numbered entry on sight. It is **26**, his age. And it splits into **XX** and **VI** — twenty years, and the sixth game he's saving for. Three readings, no exposition; he finds the split himself.

Box art leans on the split without annotating it: `X X V I` above a rule, `XX · VI` beneath. Strapline on the library card: *"you've been playing this one since 2006."*

**The payload:** two PSN gift cards, ₹1,000 and ₹2,000. ₹3,000 total, framed as exactly half the ₹6,000 needed for GTA 6 in India. The rest is his problem.

**The one hard constraint:** the date cannot move. Everything below is shaped by the fact that this runs once, live, at midnight, with no opportunity to patch.

### 1.0.1 Platform: desktop, recorded over Discord

Laptop, landscape, keyboard. Not phones.

This is the correct call and it improves the product: a console interface is designed for a television, so it reads as *right* on a large landscape screen and as a mobile port on a phone. It also changes three things concretely.

**Controls are keyboard-first.** The four PS face buttons map to four keys, shown on screen throughout. **Optional: if a controller is connected, the Gamepad API picks it up and he plays △○✕□ on actual △○✕□.** That is a genuine payoff for a PS player and a real technical flourish — but it is strictly an enhancement. Keyboard is the supported path; the gamepad path must never be required, because a controller that fails to enumerate at 12:01 AM cannot be allowed to block anything.

**Discord screen-share is a lossy video codec, and the design has to survive it.** High contrast, large type, no fine detail, no subtle gradients — compression will destroy all of it. No rapid full-screen flashing, which compresses badly and is an accessibility problem regardless.

**Audio may not survive the stream.** Unless he shares system audio, the trophy sound doesn't reach the recording. **Every trophy pop must read as complete with the sound muted.** Sound is a bonus layer, never load-bearing.

### 1.0.2 Fullscreen

Fullscreen via the Fullscreen API, and diegetically it's the right call — a console has no window chrome, and a browser tab bar sitting above the PS interface breaks the illusion instantly. In fullscreen the cursor hides during gameplay.

Four constraints:

- **It needs a user gesture.** The API refuses to fire on page load, so it hangs off a deliberate click — the boot screen's enter prompt is the natural place, framed as part of powering on the console rather than as a browser setting.
- **Escape exits fullscreen, and that is not overridable.** So `Esc` is bound to nothing in-game, and dropping out of fullscreen never interrupts a run — the segment continues, with a quiet affordance to go back in.
- **It is always optional.** If the request is denied or the browser refuses, everything still works windowed. Same rule as the gamepad: enhancement, never dependency.
- **It can break the Discord share, and this is the one that will actually bite.** If he shares a *window* rather than the whole screen, entering fullscreen can leave the capture black or frozen — on macOS especially, where fullscreen moves the window to a new Space. **He must share the entire screen, not the browser window.** This gets verified in the dress rehearsal (§10), because it will not show up in any other kind of testing.

### 1.1 The non-negotiable rule

**The page must never be the only path to the gift.** The codes stay in my notes. If anything fails on the night, I paste them into WhatsApp and it becomes a funny story about my own server.

The gift is guaranteed. The experience is the part that is allowed to fail.

---

## 2. Experience design

### 2.0 Before the night

The site is live well before the 20th. Until go-live it is a **coming-soon page**, and it is the only thing an anonymous visitor ever sees — no boot screen, no library, no hint of the structure.

**Two accounts, no signup.** Him and me, seeded from env with hashed passwords. No registration, no password reset, no recovery flow — if either of us is locked out, I fix it directly on the box. This is not a user system and must not grow into one.

| Who | Before go-live | After go-live |
|---|---|---|
| Anonymous | Coming-soon page | Coming-soon page |
| **Him** | Personalised teaser + live countdown | The console |
| **Me** (operator) | Operator dashboard + dry-run mode | Operator dashboard |

Logging him in early is deliberate: it tells him something exists and is coming for him, without leaking what. The countdown does the rest.

**Login also does real work later.** The run binds to his account rather than a browser cookie, so closing the tab, switching browsers, or moving to another machine mid-run resumes exactly where he was. On a night where he's screen-sharing to Discord, that's not hypothetical.

**The timed unlock.**

- Target is stored as a **UTC instant**, rendered in `Asia/Kolkata`. The countdown is server-driven; the client's clock is never consulted or trusted.
- **I can force-unlock from the dashboard.** Timezone handling is the single most likely thing to be wrong here, and its failure mode is his birthday not starting on his birthday. The override is the mitigation, and it gets tested (§10).
- **Dry-run mode** lets me play the full experience before the 20th without tripping the real unlock or consuming real codes.

### 2.1 The origin

Twenty years in, he has never platinumed the one game he's been playing his whole life. Today he has to earn it.

By the usual console-trophy rules the Platinum only unlocks once every other trophy is done — so the structure of the joke and the structure of the gift are the same object.

### 2.2 Flow

| Stage | What happens |
|---|---|
| **Login** | Coming-soon page until 20 Aug 00:00 IST; his account then lets him through (§2.0). |
| **Boot** | Console power-on: hum, logo bloom. |
| **Activation** | Demands an `ACTIVATION_CODE`, formatted as a PS product key (`XXXX-XXXX-XXXX`). Delivered by me, by email, as a riddle. Nothing runs without it. |
| **Profile select** | Two accounts: his, and mine — greyed out until my operator dashboard connects, then it flips to **online**. He sees me arrive. |
| **Difficulty** | KIDDIE / DEVIL. Palette shifts live as he moves between them; Devil goes red-black. Real warning copy. |
| **Install** | Fake progress bar, ~5s, joke subtitles: *copying 20 years… decompressing inside jokes… verifying trauma…* |
| **How to play** | One card, shown once (§2.3). |
| **Act I** | Segments 1–4. |
| **Checkpoint 1** | Secret code, read out by me on the call. 3 attempts. → **₹1,000 released** on my approval. |
| **Act II** | Segments 5–8. |
| **Checkpoint 2** | Second secret code, same rules. |
| **Platinum** | Full-screen trophy pop. → **₹2,000 released.** |
| **Trophy cabinet** | All trophies, run stats, closing message from me. This is the screen he screenshots. |

### 2.3 The "how to play" card

> **2 acts. 8 trophies of memory. 8 of skill.**
> Clear an act, and Kritish releases a code.
> **KIDDIE** — a fail costs you the current segment.
> **DEVIL** — a fail costs you everything.
> *Codes you've already earned are yours. Nothing takes those back.*

### 2.4 Segment structure

Each segment is **one game, then one question**. Eight segments, four per act.

| Segment | Game | Question |
|---|---|---|
| S1 | G1 — △○✕□ Simon Says | Q1 |
| S2 | G2 — Update 1 of 47 | Q2 |
| S3 | G3 — Stick Drift | Q3 |
| S4 | G4 — Trophy Run | Q4 |
| — | **Checkpoint 1 → ₹1,000** | |
| S5 | G1′ — Simon, remixed | Q5 |
| S6 | G2′ — Update, remixed | Q6 |
| S7 | G3′ — Drift, remixed | Q7 |
| S8 | G4′ — **The Platinum Run** | Q8 |
| — | **Checkpoint 2 → ₹2,000 + Platinum** | |

**Four mechanics, eight appearances.** Each debuts in Act I and returns in Act II remixed — faster, inverted, HUD stripped, sequence doubled. This is half the build of eight bespoke games and better design: he learns a mechanic, then gets tested on mastery. The Platinum Run lands as a callback rather than a new thing to figure out at minute 22.

### 2.5 The games

| # | Game | The bit |
|---|---|---|
| G1 | **△ ○ ✕ □ Simon Says** | Face-button sequence, growing each round. Instantly readable to any PS player. Server-seeded, so fully verifiable. |
| G2 | **Update 1 of 47** | A fake system update he rage-taps through. Hits 99%, drops to 1%. Pure PS5 trauma. |
| G3 | **Stick Drift** | Hold a reticle on target with the arrow keys while it drifts off on its own. DualSense joke, real skill check. Maps to an actual analogue stick when a controller is present. |
| G4 | **Trophy Run / The Platinum Run** | Rapid QTE chain. The Act II version combines all three prior mechanics and is the Devil-mode wipe point. |

All keyboard-native, with an optional gamepad path (§1.0.1). All under a minute. All legible through Discord compression.

### 2.6 The questions

Eight questions. Arc: warm open, comedy through the middle, sincerity immediately before the Platinum.

1. **Origin** — where and how it started
2. **His worst moment**
3. **His finest hour** — something he did for me
4. **The catchphrase** — a line only we say
5. **The gaming one** — a real match, a real rage-quit
6. **The betrayal** — a time he did me dirty
7. **The deep cut** — a detail only 20 years buys
8. **The sincere one** — no joke, no wrong answer

**Answers are typed, not chosen.** Four options gives a 25% guess rate, which is indefensible when Devil mode has real stakes — and typing `GTAIV` is simply more satisfying than picking it off a list. The prompt shows a blank sized to the answer.

Each question carries a list of accepted spellings. Both the submission and the accepted values are normalised — lowercased, non-alphanumerics stripped — so `GTA-4`, `gta 4` and `GTA 4` collapse to one value. The `accept` list covers what normalisation cannot: `gtaiv` and `gta4` are genuinely different strings.

```yaml
- prompt: "the game he swore he'd never buy"
  blank: "____ __"
  accept: ["GTAIV", "GTA IV", "GTA 4", "grand theft auto 4"]
  roast: "..."
```

**In Devil mode, submitting an answer requires a confirm step.** A typo costing a life is the one failure that turns this from tense into infuriating, and it is cheap to prevent without softening the stakes.

> **Open item.** Actual question content is not yet written. Kritish supplies prompt and answer; the `accept` variants are generated from those. See §11.

### 2.7 Trophies

**19 standard**, with the Platinum requiring the other 18:

- 8 × question trophies (bronze)
- 8 × game trophies (bronze in Act I, silver in Act II)
- 2 × act-completion trophies (gold)
- 1 × **Platinum**

**3 hidden**, which do not gate the Platinum and whose names stay masked until they pop: *Rage Quit* (closed the tab and came back), *Stick Drift Denier* (failed G3 three times), *Speedrun Any%*.

### 2.8 Difficulty and failure

| | Fail a game or question | Fail a checkpoint code |
|---|---|---|
| **KIDDIE** | Restart current segment. Unlimited. | 3 attempts, then lockout. No progress lost. |
| **DEVIL** | Restart current segment, **minus one life**. At zero lives, restart from S1. | Same. |

**"Restart current segment" means the whole segment** — game and question both, from the top. Failing the question does not let him retry the question alone.

**Devil lives — one pool of three for the entire run.** Not per segment, not refilled at checkpoints. Each failure costs a life and replays the segment; the third failure wipes to S1 and restores the pool to full (otherwise the second run would be unwinnable).

This is the change that makes Devil worth choosing. As originally specced, a single fluke at segment 7 ended a twenty-minute run — which is the exact failure mode that turns tension into resentment. A pool of three means early losses are cheap and late ones are terrifying, so the pressure curve builds by itself, and the HUD gets a counter that only ever goes down.

The count is config-driven (`devil_lives`), never hardcoded.

**On a Devil wipe**, segment progress and the trophies tied to segments are cleared and must be re-earned. **Code releases are not.** A wipe in Act II sends him back to S1 with his ₹1,000 still in hand; he replays both acts to reach the ₹2,000. Hidden trophies, once popped, stay popped.

**The activation gate is rate-limited but never hard-locked.** Checkpoint codes can afford to be cruel; the front door cannot. A lockout there means the whole thing dies before it starts, at midnight, with both of us on a call.

The run is at risk. The gift is not.

### 2.9 Operator dashboard

Not passive. Live run state, plus:

- **Push secret code** — release a checkpoint code to his screen
- **Approve code release** — no gift card code is ever emitted without my explicit click
- **Send notification** — free-text message that lands on his screen as a PS-style toast, mid-game, in my voice. He is screen-sharing, so it lands in the recording too
- **Force unlock** — start the night early or rescue a timezone mistake (§2.0)
- **Clear lockout** — override any gate

I'm on the call with him anyway. This puts me inside the game rather than beside it.

---

## 3. Security model

### 3.1 Threats and controls

| Control | What it stops |
|---|---|
| Codes in env secrets, never in the bundle or DB | View-source scraping |
| `ACTIVATION_CODE` at the door, out-of-band | A leaked or forwarded link being usable at all |
| Server-authoritative progress behind an HMAC-signed session | Editing localStorage to skip to the end |
| Checkpoint codes, hashed + rate-limited, 3 attempts then lockout | Brute-forcing the gates |
| Activation code, hashed + rate-limited, **no hard lockout** (§2.8) | Brute-forcing the door, without ever bricking it |
| One-time release, enforced by a DB unique constraint | Replaying the release request |
| Codes explicitly excluded from logs and error traces | The mistake people actually make |
| Operator approval required for every release | Everything else |
| Real codes injected only on the day; dev and staging run dummies | Exposure window |
| Two seeded accounts, hashed passwords, no signup or recovery flow | An auth surface existing at all |
| Coming-soon page is all an anonymous visitor ever sees | The structure leaking before the 20th |

Three codes are out-of-band and mine alone: activation, checkpoint 1, checkpoint 2. **I am physically required for him to start, to bank ₹1,000, and to finish.**

### 3.2 Honest limits

- **The last mile is unprotectable.** Once a code renders on his screen it can be screenshotted. True of every gift card ever issued.
- **This is anti-tamper, not cheat-proof.** A determined attacker could forge a plausible game result. Acceptable, because the money is not behind the games — it is behind three codes I hold and a button I press. The games protect the experience; I protect the gift.

### 3.3 Repository secrecy

Private from the first commit. Nothing public until the codes are redeemed and at least a month has passed.

The architecture staying secret is not what protects the codes — they're env vars on my instance, and they'll be spent within days. **The content is what needs hiding before the day**: the riddle, the eight questions, the trophy names, the closing message. All of it lives in one gitignored file.

---

## 4. Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | **FastAPI** + native WebSockets + SQLAlchemy/asyncpg | Daily driver. A deadline that cannot move is not the place to learn a language. |
| Frontend | **React + Vite + TypeScript** | Non-negotiably TS regardless of backend choice. |
| Type contract | **Pydantic → OpenAPI → `openapi-typescript`** | §9 |
| Database | **Neon** (managed Postgres) | Plain Postgres, no bundled features we're deliberately rebuilding. Branching is useful while iterating. |
| Deploy | **Docker Compose** on my instance, Caddy for TLS | |

**Go is explicitly out of scope for this build.** Once this ships and works, rewriting the realtime hub in Go is close to an ideal first Go project — bounded, genuinely concurrent, with a working Python implementation to diff behaviour against. That's a separate project.

---

## 5. Architecture

A modular monolith. Boundaries exist for testability and for keeping the pieces small enough to reason about — not for hypothetical contributors.

```
server/
├── core/          run state machine — acts, segments, progression,
│                  wipe rules, what's earned. Pure logic, zero I/O.
├── content/       loads + validates the YAML config via Pydantic
├── vault/         code custody and one-time release
├── gates/         out-of-band code verification, hashing, rate limits
├── realtime/      WS hub — player channel + operator channel
├── api/           thin HTTP layer
└── persistence/   repositories over Postgres

web/
├── shell/         console UI — boot, profile, library, trophies
├── games/         registry + 4 mechanics behind one interface
└── api.ts         generated, do not edit
```

**`core/` is the part that must be correct at midnight.** Pure functions, no database, no network, exhaustively tested.

**`vault/` is isolated on purpose** so that "never logged, emitted once, operator-approved" is enforced in one auditable file rather than scattered across handlers.

**`games/` share one interface** — receives config and a server seed, emits result plus telemetry. Four mechanics with eight variants needs a common shape regardless.

**`auth/`** — two seeded accounts, password hashing, session issuance, role checks, and the go-live gate. Deliberately the smallest module in the tree, and kept that way.

---

## 6. Data model

Six tables. **The codes are not among them.**

| Table | Contents |
|---|---|
| `accounts` | Two rows, seeded from env. Username, password hash, role (`player` \| `operator`) |
| `runs` | Current state: difficulty, act, segment, status, timestamps. Bound to `account_id` |
| `run_events` | Append-only log of everything — answers, game results, trophy pops, wipes, gate attempts |
| `trophies_earned` | `run_id`, `trophy_id`, `earned_at` |
| `gate_attempts` | Attempt counts and lockouts per gate |
| `code_releases` | Records *that* reward N was released, never its value. `UNIQUE (run_id, reward_id)` |

`run_events` earns its place three times over: it drives the operator dashboard, the end-screen stats, and debugging at 12:03 AM.

One-time release is enforced by the unique constraint — at the database level, not in application logic.

---

## 7. Server authority protocol

1. Server issues a **signed segment token** on segment start: segment id, nonce, expiry, and the game's **seed**.
2. Client plays. Posts result + telemetry (duration, input count, score).
3. Server validates: signature, not expired, not already consumed, result plausible against the seed.
4. Server decides pass/fail, appends to `run_events`, pops trophies, advances or wipes per §2.8.

Because the seed originates server-side, **Simon Says is exactly verifiable** — the server knows the sequence it generated and checks the entered one against it. Drift and reaction games are bounds-checked: minimum plausible duration, maximum plausible score, input count consistent with the result.

**Question answers never reach the client.** It receives prompts and choices; the correct index stays server-side.

---

## 8. Failure modes

This runs once, live, with no chance to patch.

| Failure | Behaviour |
|---|---|
| WebSocket drops | Client falls back to polling. State is server-side; reconnect resumes mid-segment. |
| He closes the tab | Signed session cookie resumes the run exactly where it was. Pops *Rage Quit*. |
| Rate-limited at a checkpoint | I clear it from the dashboard. |
| Operator dashboard breaks | A CLI path releases codes without it. |
| **Unlock doesn't fire at IST midnight** | I force-unlock from the dashboard. Timezone handling is the likeliest bug in the build. |
| **Controller doesn't enumerate** | Keyboard is the supported path; the gamepad is never required. |
| **He loses the tab or switches machines** | The run is bound to his account, not a cookie. He logs back in and resumes mid-segment. |
| Server down entirely | Codes go over WhatsApp. §1.1. |

**Every gate has an operator override.** The worst outcome in this entire design is my best friend locked out of his own birthday present by my own rate limiter.

---

## 9. How Pydantic and OpenAPI fit together

Written down because it's the seam where the two halves of the app agree with each other.

**Pydantic** is the library FastAPI is built on. Any request or response model in FastAPI is a Pydantic model:

```python
from pydantic import BaseModel

class AnswerSubmission(BaseModel):
    run_id: str
    question_index: int      # 0..7
    choice: int              # 0..3
```

It does two things that matter here. It **validates at runtime** — if the client posts `choice: "banana"`, FastAPI rejects it with a 422 before our code runs, which matters because the server is the authority and cannot trust the client. And it **describes itself**, which lets FastAPI publish a machine-readable description of the whole API.

**That description is OpenAPI** — the JSON at `/openapi.json` that FastAPI's `/docs` page is just a rendering of.

**`openapi-typescript`** reads that JSON and generates matching TypeScript types as a build step:

```
npx openapi-typescript http://localhost:8000/openapi.json -o web/src/api.ts
```

Pydantic stays the single source of truth; the frontend's types are a build artifact rather than a hand-maintained copy. Rename a field and the frontend refuses to compile until the call site is fixed — instead of a silent 422 at 12:04 AM.

**The one seam this doesn't cover:** WebSocket messages don't go through OpenAPI. Those need discriminated-union Pydantic models with a hand-written TypeScript mirror. Every WS message type stays in exactly one file on each side so drift is easy to spot.

---

## 10. Testing and deployment

**Tests, in priority order:**

1. **`core/` state machine — exhaustive.** Every combination of difficulty × failure point. A bug here ruins the night.
2. **`vault/`** — one-time release holds under concurrent requests; codes never appear in log output (asserted, not assumed).
3. **`gates/`** — rate limiting, lockout, operator override.
4. **Two end-to-end paths** — a clean run, and a Devil wipe in Act II that correctly retains the ₹1,000.

5. **The timed unlock** — that `Asia/Kolkata` midnight resolves to the intended UTC instant, that the gate holds one minute before, opens one minute after, and that force-unlock overrides both.

**Above all: a full dress rehearsal on staging, on the actual laptop, in fullscreen, screen-sharing to Discord, with dummy codes, several days early.** Higher value than every unit test listed. The Discord leg is not optional — compression artefacts, missing system audio, and fullscreen killing a window-capture (§1.0.2) are exactly the class of problem that appears only in the real setup.

**Deployment:** Docker Compose — `api` (FastAPI + uvicorn), `web` (static build), Caddy in front for automatic TLS. Neon sits outside compose as managed Postgres. Secrets from a gitignored `.env`. A health endpoint, so I can confirm the thing is alive before sending the link.

---

## 11. Open items

Content only I can write, in rough order of how much it blocks:

- [ ] **The eight questions** — prompts, choices, correct answers, and the roast copy for wrong answers.
- [ ] **The riddle** that delivers `ACTIVATION_CODE` by email.
- [ ] **Trophy names** — all 19 standard, plus the 3 hidden.
- [ ] **The closing message** on the trophy cabinet screen.
- [ ] **Coming-soon copy**, and the personalised variant he sees once logged in.
- [ ] Original trophy art and sound. Recreate the feel; do not ship Sony's assets.

None of these block implementation — everything builds against the config schema and gets filled in later. All of them block the 20th.

## 11.1 Schedule

**12 days.** If the build runs late, cut in this order, ending at the line that must never be crossed:

1. Hidden trophies, gamepad support, the notification button
2. Two of the four game mechanics — ship two mechanics across four variants each
3. The operator dashboard, degrading to the CLI path (§8)
4. — **never below this line** —
5. Boot → activation → 8 segments → checkpoint codes → code release

## 12. Out of scope

Deferred to the public release, no earlier than **late September 2026**:

- Config-driven generalization for other recipients
- Swappable themes, plugin APIs, reward providers
- Example configs, contributor documentation, licensing, public README
- The Go rewrite of the realtime hub

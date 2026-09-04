# Music tracks — DROP FOUR FILES HERE

Four loops cover all nine bed states (see `BED_TRACK_FOR` in
`web/src/lib/audio.ts`). A missing file is **silent** — never substituted —
so the audio bench at `/audio-preview.html` reports which ones are absent.

| file | used by | what to look for |
|---|---|---|
| `menu.mp3` | boot, calm, kiddie, question | Calm, sparse, ambient. Sits under a voice line without competing. This one plays the longest — pick the one you could hear for ten minutes. |
| `tense.mp3` | devil, life-lost | Darker, heavier, same tempo family as `menu` so the Devil swap reads as the room changing, not the soundtrack changing. |
| `game.mp3` | in-game | Forward motion, a pulse. No strong melody — it has to leave room for the game's own sound effects. |
| `triumph.mp3` | checkpoint, platinum | Warm, resolving. The two moments that pay off. |

**Format:** anything a browser decodes — mp3, m4a, ogg. Name them exactly as
above (or edit `BED_TRACKS` in `audio.ts`).

**Length:** 60–120s each, longer is better. A short loop announces itself
over an hour-long run.

**Looping:** seamless is ideal but not required — the loop point is
crossfaded, not butt-joined.

**Mix:** the bed sits at −20dB under everything else and ducks a further 6dB
under narration, so quiet, unmastered, "ambient bed" versions work better
here than loud mastered ones. If a track has a big intro, trim it: the file
loops from its own start.

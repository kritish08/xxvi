// The screen between "he clicked sign in" and "the console is on screen".
//
// MEASURED, NOT GUESSED: from the sign-in click, the gate disappeared at
// 2.6s and the boot screen appeared at 8.1s — 5.5 seconds of a completely
// black window with nothing on it at all. Two `return null`s stacked up to
// produce that: App's `<Suspense fallback={null}>` while the Console chunk
// loads, and Console's own `if (!run) return null` while the first
// `/api/run` resolves against a Neon compute that may be cold.
//
// On the night that is him clicking sign in, on a Discord stream, and
// watching a black screen for five seconds. He would reasonably conclude it
// was broken and start clicking things.
//
// Deliberately WORDLESS. This renders in the main chunk, which is the bundle
// an anonymous visitor downloads (see run-client.ts's header and
// tests/build-leak.test.ts) — so it carries no title, no vocabulary, nothing
// to read. A moving indicator says "working" without saying anything at all.

export function Loading() {
  return (
    <main className="shell shell--loading" aria-busy="true" aria-label="loading">
      <div className="loading__bar" />
    </main>
  );
}

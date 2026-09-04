// THE LEAK THIS TEST EXISTS TO CATCH DOES NOT SHOW UP IN THE RENDERED DOM.
//
// app.test.tsx and comingsoon.test.tsx already assert an anonymous
// visitor's rendered page contains none of the structure words. Both pass
// today, and both are structurally blind to the actual bug: everything
// those tests render comes from React's virtual DOM, which has no idea
// what OTHER code shipped in the same JavaScript file. A component that is
// never rendered can still ship, in full, to a visitor who never signs in
// -- readable in devtools, no rendering required.
//
// That is exactly what happened here before this task: `Console` (and
// everything it pulls in transitively -- shell/*, games/*, and the
// run-phase half of the old lib/client.ts) was a plain, eager import in
// App.tsx. Vite bundles an eagerly-imported module into the SAME chunk as
// the entry point regardless of whether a given render path ever mounts
// it, so `dist/assets/index-*.js` -- the one file `dist/index.html`
// actually references, i.e. the one file every visitor's browser
// downloads before App.tsx has decided who they are -- carried the
// library-card strapline, the title, trophy vocabulary, and every
// `/api/run/*` route string in plain text. Opening devtools' Network or
// Sources tab and reading that file was enough to spoil the surprise,
// regardless of what the coming-soon page rendered on screen.
//
// The fix (App.tsx's `React.lazy(() => import("./Console"))` /
// `import("./Operator")`, and splitting lib/client.ts so the run-phase
// routes live in lib/run-client.ts, imported only from behind the gate)
// moves that whole chunk behind a dynamic import that is never requested
// until the gate is actually open. This test is the only thing in the
// suite that would notice a regression: it runs the real production build
// and inspects the real output files, the same way a curious visitor's
// devtools would.
//
// WORD LIST -- chosen deliberately, not copied wholesale from the DOM
// tests' LEAKS list. A DOM test's fixture is small, curated rendered text,
// so short generic words like "act" or "game" are safe to grep there. A
// real production bundle also contains React, ReactDOM, and every other
// dependency, fully minified -- grepping *that* for a short common
// substring is close to guaranteed to false-positive (React's own
// hydration internals use the literal identifier `Segment`, which is why
// this file does NOT include the bare word "segment", even though the
// task brief that first found this leak did use it in an exploratory,
// human-reviewed one-off `grep`). Every entry below is either:
//   - a route path, which by construction contains `/api/run/` and cannot
//     collide with anything in a third-party library, or
//   - a piece of vocabulary distinctive enough (a whole phrase, a rare
//     word, a capitalised proper noun used nowhere else in the app) that a
//     coincidental match in unrelated minified code is implausible.
const STRUCTURE_LEAKS = [
  // The title. Written as a contiguous "XXVI" in shell/TrophyCabinet.tsx
  // ("XXVI · trophies") and shell/Boot.tsx ("XXVI console") -- unlike the
  // library card's boxart title, which is deliberately &nbsp;-split
  // letter-by-letter and so never appears as this contiguous substring in
  // the first place (see shell/Install.tsx's own comment on why).
  "XXVI",
  // The library card's strapline (shell/Install.tsx). Distinctive as a
  // whole phrase; "since 2006" cannot appear by coincidence in library
  // code.
  "since 2006",
  // Trophy vocabulary. Both are specific enough that no dependency in this
  // project's tree has a legitimate reason to contain either.
  "platinum",
  "trophy",
  // Every mutating or fetching run-phase route (lib/run-client.ts). Each
  // one only exists in this app's own source -- there is no library on
  // npm that would emit any of these exact paths.
  "/api/run",
  "/api/run/activate",
  "/api/run/profile",
  "/api/run/difficulty",
  "/api/run/installed",
  "/api/run/howto",
  "/api/run/segment/start",
  "/api/run/segment/game",
  "/api/run/segment/answer",
  "/api/run/checkpoint",
] as const;

import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const distDir = join(webRoot, "dist");
const assetsDir = join(distDir, "assets");

/** Every `<script type="module" src="...">` and `<link rel="modulepreload"
 *  href="...">` in dist/index.html -- i.e. every JS file a browser
 *  downloads before App.tsx has run a single line, before there is any
 *  session to branch on. This is the "anonymous bundle": whatever a
 *  visitor's devtools would show with zero interaction, zero login, zero
 *  clicks. Any file NOT in this set (today, that's Console-*.js and
 *  Operator-*.js) is only ever fetched by a dynamic `import()` that fires
 *  after App.tsx has already decided the visitor is authenticated and past
 *  the gate -- see App.tsx's `React.lazy` calls.
 */
function eagerEntryFiles(): string[] {
  const html = readFileSync(join(distDir, "index.html"), "utf8");
  const files: string[] = [];
  const pattern = /<(?:script[^>]*\stype="module"[^>]*\ssrc|link[^>]*\srel="modulepreload"[^>]*\shref)="([^"]+)"/g;
  for (const match of html.matchAll(pattern)) {
    files.push(match[1].replace(/^\//, ""));
  }
  return files;
}

describe("production build — the anonymous bundle carries no structure", () => {
  // The build genuinely runs `tsc -b && vite build` (see package.json); on
  // this project that's ~2s, but CI machines vary, and this is the one
  // test in the suite allowed to be slow in exchange for testing the one
  // thing nothing else here can see.
  it(
    "ships none of XXVI's structure — title, strapline, trophy vocabulary, or run-phase routes — in the bundle an anonymous visitor downloads before login",
    () => {
      execFileSync("npm", ["run", "build"], { cwd: webRoot, stdio: "pipe" });

      expect(existsSync(distDir)).toBe(true);
      const jsFiles = readdirSync(assetsDir).filter((f) => f.endsWith(".js"));
      expect(jsFiles.length).toBeGreaterThan(0);

      const eager = eagerEntryFiles().filter((f) => f.endsWith(".js"));
      expect(eager.length).toBeGreaterThan(0);

      // Sanity check on the sanity check: if this ever equals the FULL set
      // of js chunks, code-splitting silently stopped happening (e.g. the
      // React.lazy() calls in App.tsx regressed to static imports) and the
      // assertions below would still pass for the wrong reason — there'd
      // be nothing left for them to catch. Confirm at least one chunk
      // exists that ISN'T eagerly loaded.
      expect(eager.length).toBeLessThan(jsFiles.length);

      for (const file of eager) {
        const path = join(webRoot, "dist", file);
        expect(existsSync(path), `${file} is referenced by dist/index.html but was not emitted`).toBe(true);
        const code = readFileSync(path, "utf8");
        for (const leak of STRUCTURE_LEAKS) {
          expect(
            code.includes(leak),
            `"${leak}" was found in ${file}, a file dist/index.html loads before any ` +
              `login or gate check. That file ships to EVERY anonymous visitor on ` +
              `first paint, readable in devtools regardless of what's on screen — this ` +
              `is the exact leak this test exists to catch (see this file's header). ` +
              `Something now imports a run-phase or Console/Operator module eagerly ` +
              `instead of behind React.lazy(); trace the import graph from App.tsx and ` +
              `move the offending import behind the gate.`,
          ).toBe(false);
        }
      }

      // The words above must still exist SOMEWHERE — in the lazy chunks —
      // or this test would pass merely because the content was deleted,
      // not because it was correctly gated behind the lazy boundary.
      const allCode = jsFiles.map((f) => readFileSync(join(assetsDir, f), "utf8")).join("\n");
      for (const leak of ["XXVI", "platinum", "trophy", "/api/run/segment/game"]) {
        expect(allCode.includes(leak), `expected "${leak}" to still exist in the lazy-loaded chunks`).toBe(true);
      }
    },
    120_000,
  );
});

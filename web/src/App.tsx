import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import "./App.css";
import { ComingSoon } from "./ComingSoon";
import { Loading } from "./Loading";
import { Login } from "./Login";
import { api, type ContentView, type SessionInfo } from "./lib/client";

// Lazy, not a static import: Console (and everything it pulls in --
// shell/*, games/*, lib/run-client.ts) is the entire back-half of the
// product -- trophy names, segment/act vocabulary, the run-phase route
// strings. A static `import { Console } from "./Console"` here would put
// all of that in THIS file's chunk, which is exactly the chunk an
// anonymous visitor downloads to see the coming-soon page -- readable in
// devtools before he ever signs in, regardless of what the rendered DOM
// says. `React.lazy` + Vite's automatic code-splitting on dynamic
// `import()` is what keeps it out: the Console chunk is only ever
// requested once this file actually renders `<Console />`, which never
// happens before the gate is open for an authenticated player.
const Console = lazy(() => import("./Console").then((m) => ({ default: m.Console })));
// Operator.tsx is owned by a parallel task; same reasoning applies to it
// independently -- an operator's own dashboard has no business shipping in
// the anonymous bundle either, even though its content isn't the
// birthday-night secret. Referenced by path only, never imported eagerly.
const Operator = lazy(() => import("./Operator").then((m) => ({ default: m.Operator })));

/**
 * Task 15 owns this file and is the single place in the app that branches
 * on `{ authenticated, role, live }`. Every screen below it just renders
 * what it is told to -- this is the only file that decides which screen
 * that is.
 *
 * Routing, in priority order:
 *   1. An authenticated operator always lands on the operator surface,
 *      live or not -- they run the event, so they can't be stuck behind
 *      their own gate.
 *   2. Anyone else who is not authenticated, or is authenticated but the
 *      gate isn't open yet, sees the coming-soon page. Only the login form
 *      is layered on top of it, and only while unauthenticated.
 *   3. An authenticated player once the server says `live` gets the real
 *      console (Task 16).
 */
export default function App() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [content, setContent] = useState<ContentView | null>(null);
  // Set only once `api.getContent()`'s own bounded retry (lib/client.ts)
  // has given up. Before that, a transient failure just keeps `content`
  // null while a retry is still in flight -- this only flips once there is
  // truly nothing left to wait for.
  const [contentError, setContentError] = useState(false);

  const refreshSession = useCallback(async () => setSession(await api.getSession()), []);

  useEffect(() => {
    void refreshSession();
    // Copy is fetched once -- it's static site content, not run state.
    // `api.getContent()` already retries transient failures with backoff
    // (lib/client.ts); a final rejection here means retries are exhausted,
    // not a first-try blip, so it surfaces rather than leaving the screen
    // blank forever with nothing to go on (see `contentError` below).
    void api
      .getContent()
      .then(setContent)
      .catch(() => setContentError(true));

    // The countdown on screen is cosmetic. This poll is what actually
    // re-syncs `live` and `seconds_until_live` against the server, which is
    // the only thing that ever decides the gate is open -- the client's
    // own clock never does.
    const poll = window.setInterval(refreshSession, 30_000);
    return () => window.clearInterval(poll);
  }, [refreshSession]);

  // Never a blank window while the first session/content round-trip is in
  // flight — see Loading.tsx for the 5.5s of black screen this replaces.
  if (!session) return <Loading />;

  if (!content) {
    // No blank screen with nothing to act on: content-fetch retries
    // (lib/client.ts) are exhausted and there is still nothing to render.
    // Generic on purpose -- this can be an anonymous visitor's screen too,
    // so it gets the same "reveal nothing" treatment as the coming-soon
    // copy itself, while still being something a person watching the
    // stream (the operator, or him) can actually see and act on.
    if (contentError) {
      return (
        <main className="shell shell--error">
          <p className="label">error</p>
          <p>something went wrong loading this page. try refreshing.</p>
        </main>
      );
    }
    return <Loading />;
  }

  if (session.authenticated && session.role === "operator") {
    return (
      <Suspense fallback={<Loading />}>
        <Operator />
      </Suspense>
    );
  }

  if (!session.authenticated || !session.live) {
    return (
      <main className="shell shell--gate">
        <ComingSoon session={session} copy={content.copy.coming_soon} teaser={content.copy.teaser} />
        {!session.authenticated && <Login onSuccess={refreshSession} />}
      </main>
    );
  }

  return (
    <Suspense fallback={<Loading />}>
      <Console />
    </Suspense>
  );
}

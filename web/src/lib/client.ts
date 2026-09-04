// Typed wrappers over the PRE-GATE routes only: `/api/session`,
// `/api/content`, `/api/auth/login`, `/api/auth/logout`. This is the one
// api module the main entry chunk is allowed to import eagerly (from
// App.tsx and Login.tsx) -- everything it references (this file, lib/http,
// their shared types) ships to an anonymous visitor before any gate.
//
// Every run-phase route (`startSegment`, `submitGame`, `submitAnswer`,
// `submitCheckpoint`, `activate`, and friends) used to live here too, but
// that made this file, and everything it imports, unavoidably eager: those
// route strings (`/api/run/segment/game`, `/api/run/howto`, ...) shipped in
// the SAME bundle an anonymous visitor downloads for the coming-soon page,
// readable in devtools before he ever signs in. They now live in
// lib/run-client.ts, which nothing in the pre-gate render path imports --
// see that file's header for the full contract. Splitting the module
// changes where each function lives, not its signature: every method below
// keeps its original name and shape.
//
// The request/response shapes below are type ALIASES onto src/api.ts's
// generated `components["schemas"]` -- not hand-duplicated interfaces --
// and every request body is checked against its generated schema with
// `satisfies`. This is deliberate: it is what makes a Pydantic field rename
// break `npm run build` here instead of failing silently at runtime.

import type { components } from "../api";
import { ApiError, call, post } from "./http";

export type SessionInfo = components["schemas"]["SessionInfo"];
// Task 15 is the first task that needs /api/content (site copy, gated on
// nothing -- readable pre-login), so it adds the wrapper here. Tasks 20/21
// reuse it for trophy names and closing copy.
export type ContentView = components["schemas"]["ContentView"];
/** One trophy as the content route serves it — hidden names already masked
 *  server-side (api/content_routes.py), so this is safe to render as-is. */
export type TrophyView = ContentView["trophies"][number];

// Re-exported so existing call sites (`import { ApiError } from
// "./lib/client"`) keep working unchanged -- ApiError itself is generic
// transport plumbing (lib/http.ts) with nothing in it worth gating.
export { ApiError };

// Bounded retry + backoff for GET /api/content. A transient failure here
// used to be swallowed silently (App.tsx's `.catch(() => undefined)`),
// which left the ENTIRE app blank forever -- not just the coming-soon
// page, the operator's own dashboard too, since both wait on `content`
// before rendering anything (App.tsx: `if (!session || !content) return
// null`). On a night when nobody can debug it, "blank and no error" is the
// worst possible failure mode. Three retries with growing backoff gives a
// flaky connection room to recover; a caller still sees a rejected promise
// if all of them fail, so it can show *something* rather than stay blank
// (see App.tsx's `contentError` state).
const CONTENT_RETRY_DELAYS_MS = [500, 1500, 4000];

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function getContentWithRetry(): Promise<ContentView> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await call<ContentView>("/api/content");
    } catch (error) {
      if (attempt >= CONTENT_RETRY_DELAYS_MS.length) throw error;
      await delay(CONTENT_RETRY_DELAYS_MS[attempt]);
    }
  }
}

export const api = {
  getSession: () => call<SessionInfo>("/api/session"),
  // Public: readable by an anonymous visitor, which is exactly who the
  // coming-soon page serves it to (see xxvi/api/content_routes.py).
  getContent: getContentWithRetry,
  login: (username: string, password: string) =>
    post<components["schemas"]["LoginResponse"]>(
      "/api/auth/login",
      { username, password } satisfies components["schemas"]["LoginRequest"],
    ),
  logout: () => post<{ ok: boolean }>("/api/auth/logout"),
};

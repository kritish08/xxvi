// Single source of truth for "how many trophies are there."
//
// The standard (non-hidden) trophy total is a computed value derived from
// GET /api/content (server/xxvi/content_routes.py's ContentView), never a
// hardcoded constant. Task 16's library card (shell/Install.tsx) originally
// hardcoded 16, reasoning from the how-to-play copy ("8 trophies of memory,
// 8 of skill") — but that copy only ever describes the 16 *segment*
// trophies. The real standard total also includes the 2 act trophies and
// Platinum (19 in the current content: 8 question + 8 game + 2 act +
// platinum), and — deliberately — excludes the extra hidden trophies,
// which don't gate Platinum and aren't part of the promise made on the
// library card. The act trophies and Platinum are deliberately absent from
// the how-to-play copy because Platinum is the surprise; that's exactly
// why the copy can't be trusted as the source for this number.
//
// Both the library card and TrophyCabinet count standard trophies the same
// way, via `standardTrophyCount`, so the two surfaces cannot silently
// disagree with each other the way the hardcoded constant disagreed with
// the server.

import { api, type ContentView } from "./client";

export type TrophySummary = ContentView["trophies"][number];

/** Count of standard (non-hidden) trophies. Pure and synchronous so it's
 *  trivial to test against a fixture, and so TrophyCabinet (which already
 *  has a trophies list as a prop) and the library card (which fetches its
 *  own) derive the same number from the same rule rather than each
 *  re-deriving their own arithmetic. */
export function standardTrophyCount(trophies: readonly TrophySummary[]): number {
  return trophies.filter((t) => !t.hidden).length;
}

/**
 * Fetches /api/content and returns just the standard trophy count.
 * Swallows any failure — network error, non-2xx, malformed response — and
 * resolves to `null` rather than throwing. A transient /api/content
 * failure must degrade the library card to showing no count, never a
 * wrong one (0, or a stale hardcoded number) and never a blank screen; the
 * caller is responsible for rendering that `null` as "no count shown."
 */
export async function fetchStandardTrophyCount(): Promise<number | null> {
  try {
    const content = await api.getContent();
    return standardTrophyCount(content.trophies);
  } catch {
    return null;
  }
}

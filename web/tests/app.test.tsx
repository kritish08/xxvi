import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";

const anonymousSession = { authenticated: false, role: null, live: false, seconds_until_live: 3600 };
const authenticatedPlayerPreLive = {
  authenticated: true,
  role: "player",
  live: false,
  seconds_until_live: 90,
};
const authenticatedOperator = { authenticated: true, role: "operator", live: false, seconds_until_live: 90 };

const content = {
  copy: {
    coming_soon: "not open yet.",
    teaser: "you already know what this is.",
    how_to_play: "unused here",
    closing: "unused here",
  },
  trophies: [],
};

const { getSessionMock, getContentMock } = vi.hoisted(() => ({
  getSessionMock: vi.fn(),
  getContentMock: vi.fn(),
}));

vi.mock("../src/lib/client", () => ({
  api: { getSession: getSessionMock, getContent: getContentMock, login: vi.fn() },
}));

// Operator.tsx is its own React.lazy chunk (Task 28) whose dashboard (Task
// 21) is real, not a placeholder: it waits on `GET /api/operator/state`
// (lib/operator-api.ts) before it renders anything at all
// (`if (!state) return null`) and opens its own `/api/ws/operator` socket
// (lib/ws.ts -> the real `WebSocket`) alongside that. Neither is mocked by
// this file's `../src/lib/client` mock above (operator-api.ts is a
// deliberately separate module — see its own header comment), so without
// stubs here that fetch/socket hit real, unmocked globals in jsdom, never
// resolve, and `state` stays null forever — the operator test below would
// wait for DOM that can never appear. Same fetch/WebSocket stub pattern as
// tests/operator.test.tsx.
const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);
vi.stubGlobal("WebSocket", class { close() {} } as never);

// The words a reviewer greps the rendered DOM for. An anonymous visitor
// must be able to find none of them, anywhere on the page -- not the
// title, not trophies, segments, acts, the platinum, that there are games,
// an install step, or a console at all.
const LEAKS = ["trophy", "segment", "act", "platinum", "xxvi", "game", "install", "console"];

describe("App — routing on {authenticated, role, live}", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("shows an anonymous visitor only the generic coming-soon copy and a login form", async () => {
    getSessionMock.mockResolvedValue(anonymousSession);
    getContentMock.mockResolvedValue(content);

    render(<App />);
    await waitFor(() => expect(screen.getByText("not open yet.")).toBeDefined());

    // The login form is present (unauthenticated)...
    expect(screen.getByLabelText("user")).toBeDefined();
    // ...but nothing personalised is.
    expect(screen.queryByLabelText("time remaining")).toBeNull();
    expect(screen.queryByText("you already know what this is.")).toBeNull();

    const text = document.body.textContent?.toLowerCase() ?? "";
    for (const leak of LEAKS) {
      expect(text).not.toContain(leak);
    }
  });

  it("personalises for an authenticated player before go-live, with no login form", async () => {
    getSessionMock.mockResolvedValue(authenticatedPlayerPreLive);
    getContentMock.mockResolvedValue(content);

    render(<App />);
    await waitFor(() => expect(screen.getByText("you already know what this is.")).toBeDefined());

    expect(screen.getByLabelText("time remaining").textContent).toBe("00:00:01:30");
    expect(screen.queryByLabelText("user")).toBeNull();
  });

  it("sends an authenticated operator to their own dashboard, not the player flow", async () => {
    getSessionMock.mockResolvedValue(authenticatedOperator);
    getContentMock.mockResolvedValue(content);
    // GET /api/operator/state — the real dashboard's first paint gate.
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ live_forced: false, runs: [] }),
    });

    render(<App />);
    // Two async boundaries stand between this render and the dashboard
    // showing anything: the `React.lazy` chunk resolving (Task 28), and
    // then Operator.tsx's own `GET /api/operator/state` call resolving
    // (Task 21 — `if (!state) return null`, so the component renders
    // nothing at all until that fetch is back). `findByRole` polls past
    // both rather than asserting on the very next tick.
    expect(await screen.findByRole("heading", { name: "console", level: 1 })).toBeDefined();
    // Content only the real dashboard renders — not a synchronous
    // placeholder standing in for it.
    expect(screen.getByText("operator")).toBeDefined();
    expect(screen.getByText("no run yet.")).toBeDefined();

    expect(screen.queryByText("not open yet.")).toBeNull();
    expect(screen.queryByLabelText("user")).toBeNull();
    expect(screen.queryByLabelText("time remaining")).toBeNull();
  });
});

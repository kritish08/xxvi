import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Operator } from "../src/Operator";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);
vi.stubGlobal("WebSocket", class { close() {} } as never);

const baseRun = {
  id: 1,
  difficulty: "devil",
  phase: "checkpoint",
  segment: 4,
  cleared_segments: [1, 2, 3, 4],
  released_rewards: [] as number[],
};

function stateWith(overrides: Partial<typeof baseRun> = {}, extra: Record<string, unknown> = {}) {
  return {
    live_forced: false,
    runs: [{ ...baseRun, ...overrides, ...extra }],
  };
}

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body };
}

describe("Operator", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the live run and its phase and difficulty", async () => {
    fetchMock.mockResolvedValue(jsonResponse(stateWith()));
    render(<Operator />);
    expect(await screen.findByRole("heading", { name: "checkpoint", level: 2 })).toBeDefined();
    expect(screen.getByText(/devil/)).toBeDefined();
  });

  it("shows segment progress and cleared-segment count without a dense table", async () => {
    // Distinct from the segment number on purpose, so the two stats are
    // independently assertable rather than coincidentally identical.
    fetchMock.mockResolvedValue(jsonResponse(stateWith({ cleared_segments: [1, 2, 3] })));
    render(<Operator />);
    await screen.findByRole("heading", { name: "checkpoint", level: 2 });
    expect(screen.getByText(/4 · 8/)).toBeDefined(); // segment 4 of 8
    expect(screen.getByText(/3 · 8/)).toBeDefined(); // 3 cleared of 8
  });

  it("does not render lives or trophies when there's nothing meaningful to show (no fabricated data)", async () => {
    // `lives: null` (Kiddie / not-yet-Devil, xxvi/api/operator_routes.py)
    // and `trophies: []` (nothing earned yet) are both real, valid server
    // responses now (task 29) — this is not a missing-field case, it's the
    // ordinary early-run state. A dashboard that showed "lives: null" or
    // "trophies: 0" would be a worse, more confusing bit of chrome than
    // showing nothing.
    fetchMock.mockResolvedValue(jsonResponse(stateWith({}, { lives: null, trophies: [] })));
    render(<Operator />);
    await screen.findByRole("heading", { name: "checkpoint", level: 2 });
    expect(screen.queryByText(/^lives$/i)).toBeNull();
    expect(screen.queryByText(/^trophies$/i)).toBeNull();
  });

  it("also renders nothing for lives/trophies when a caller's payload omits the fields entirely", async () => {
    // Defence in depth: OperatorRunSummary now types these as always
    // present (the real server always sends them), but Operator.tsx still
    // guards with `?.`/`!= null` rather than assuming the runtime payload
    // matches the type exactly.
    fetchMock.mockResolvedValue(jsonResponse(stateWith()));
    render(<Operator />);
    await screen.findByRole("heading", { name: "checkpoint", level: 2 });
    expect(screen.queryByText(/^lives$/i)).toBeNull();
    expect(screen.queryByText(/^trophies$/i)).toBeNull();
  });

  it("shows lives when the run has a Devil-mode pool", async () => {
    fetchMock.mockResolvedValue(jsonResponse(stateWith({}, { lives: 2, trophies: [] })));
    render(<Operator />);
    await screen.findByRole("heading", { name: "checkpoint", level: 2 });
    expect(screen.getByText(/^lives$/i)).toBeDefined();
    expect(screen.getByText("2")).toBeDefined();
  });

  it("shows the earned trophy count, sourced from the trophies the server actually reports", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(stateWith({}, { lives: null, trophies: ["first-blood", "speedrunner"] })),
    );
    render(<Operator />);
    await screen.findByRole("heading", { name: "checkpoint", level: 2 });
    expect(screen.getByText(/^trophies$/i)).toBeDefined();
    expect(screen.getByText("2")).toBeDefined();
  });

  it("requires a confirmation before releasing a code, and shows which run/reward it is for", async () => {
    fetchMock.mockResolvedValue(jsonResponse(stateWith()));
    render(<Operator />);
    await userEvent.click(await screen.findByRole("button", { name: /release ₹|release reward 1/i }));

    // The confirm step names the exact run and reward (scoped to the
    // dialog itself -- the trigger button and reward row behind it also
    // contain the substring "reward 1").
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByText(/reward 1/i)).toBeDefined();
    expect(dialog.getByText(/run 1/i)).toBeDefined();

    // Nothing is posted until the confirm step is taken.
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/approve"))).toBe(false),
    );
    await userEvent.click(screen.getByRole("button", { name: /confirm/i }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/approve"))).toBe(true),
    );
  });

  it("cancelling the confirm dialog posts nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(stateWith()));
    render(<Operator />);
    await userEvent.click(await screen.findByRole("button", { name: /release reward 1/i }));
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/approve"))).toBe(false);
  });

  // The core invariant: he is screen-sharing to Discord, so a released
  // code must never appear on screen unless he deliberately asks for it.
  it("does not render a released code's value until he explicitly reveals it", async () => {
    let approved = false;
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes("/approve")) {
        approved = true;
        return Promise.resolve(
          jsonResponse({ type: "code_released", reward_id: 1, label: "Reward 1", code: "SECRET-CODE-123" }),
        );
      }
      // Mirrors the real ledger: once /approve has actually gone out, a
      // fresh GET /state reports the reward as released too.
      return Promise.resolve(
        jsonResponse(stateWith({ released_rewards: approved ? [1] : [] })),
      );
    });
    render(<Operator />);
    await userEvent.click(await screen.findByRole("button", { name: /release reward 1/i }));
    await userEvent.click(screen.getByRole("button", { name: /confirm release/i }));

    // The approve call has gone out, but the raw code must not be in the DOM yet.
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/approve"))).toBe(true),
    );
    expect(screen.queryByText("SECRET-CODE-123")).toBeNull();

    // Only after the deliberate "reveal code" click does the value render.
    const revealButton = await screen.findByRole("button", { name: /reveal code/i });
    expect(screen.queryByText("SECRET-CODE-123")).toBeNull();
    await userEvent.click(revealButton);
    expect(await screen.findByText("SECRET-CODE-123")).toBeDefined();

    // And it can be hidden again just as deliberately.
    await userEvent.click(screen.getByRole("button", { name: /hide code/i }));
    expect(screen.queryByText("SECRET-CODE-123")).toBeNull();
  });

  it("reads released state from what the server reports (the ledger), not from a client-side guess", async () => {
    // released_rewards here already reflects the vault/ledger per
    // xxvi/api/operator_routes.py's own comment -- the client must take
    // that at face value, not recompute it.
    fetchMock.mockResolvedValue(jsonResponse(stateWith({ released_rewards: [1] })));
    render(<Operator />);
    await screen.findByRole("heading", { name: "checkpoint", level: 2 });
    expect(screen.getAllByText(/^released$/i).length).toBeGreaterThan(0);
    // No release button remains for the already-released reward.
    expect(screen.queryByRole("button", { name: /release reward 1/i })).toBeNull();
    // And since this dashboard never called /approve itself, it honestly
    // has no code to reveal for it.
    expect(screen.queryByRole("button", { name: /reveal code/i })).toBeNull();
  });

  it("resets a locked gate's attempts with a single click and no confirm step", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes("/unlock-gate")) return Promise.resolve(jsonResponse({ ok: true }));
      return Promise.resolve(jsonResponse(stateWith()));
    });
    render(<Operator />);
    await userEvent.click(await screen.findByRole("button", { name: /reset checkpoint 1 attempts/i }));
    // No dialog interposed -- the call goes straight out.
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/unlock-gate"))).toBe(true),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("sends a free-text toast for the run", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes("/toast")) return Promise.resolve(jsonResponse({ delivered: 1 }));
      return Promise.resolve(jsonResponse(stateWith()));
    });
    render(<Operator />);
    const input = await screen.findByPlaceholderText(/message for his screen/i);
    await userEvent.type(input, "you've got this!");
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/toast"));
      expect(call).toBeDefined();
      const body = JSON.parse(String(call?.[1]?.body));
      expect(body).toEqual({ run_id: 1, text: "you've got this!" });
    });
  });

  it("requires confirmation before forcing go-live, and keeps it separate from the routine controls", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes("/force-golive")) return Promise.resolve(jsonResponse({ live: true }));
      return Promise.resolve(jsonResponse(stateWith()));
    });
    render(<Operator />);
    await userEvent.click(await screen.findByRole("button", { name: /force go-live/i }));
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/force-golive"))).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: /confirm force go-live/i }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/force-golive"))).toBe(true),
    );
  });

  it("shows a static 'forced' readout instead of a repeatable button once live_forced is true", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ live_forced: true, runs: [baseRun] }));
    render(<Operator />);
    expect(await screen.findByText(/forced/i)).toBeDefined();
    expect(screen.queryByRole("button", { name: /^force go-live$/i })).toBeNull();
  });
});

describe("Operator — the checkpoint bypass", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("is not offered when the run is not at a checkpoint", async () => {
    fetchMock.mockResolvedValue(jsonResponse(stateWith({ phase: "game", segment: 2 })));
    render(<Operator />);
    await screen.findByRole("heading", { name: "game", level: 2 });
    // A live button that can only ever 409 is worse than no button at the
    // moment he needs to trust the dashboard.
    expect(
      screen.queryByRole("button", { name: /pass checkpoint without the code/i }),
    ).toBeNull();
  });

  it("requires a confirm before it hands over a card, and cancel calls nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(stateWith()));
    render(<Operator />);
    await userEvent.click(
      await screen.findByRole("button", { name: /pass checkpoint without the code/i }),
    );
    expect(await screen.findByText(/without the phrase/i)).toBeDefined();

    const callsBefore = fetchMock.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: /^cancel$/i }));
    expect(
      fetchMock.mock.calls.slice(callsBefore).some(([url]) => String(url).includes("pass-checkpoint")),
    ).toBe(false);
  });

  it("passes the checkpoint on confirm and keeps the returned code, still behind reveal", async () => {
    let bypassed = false;
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes("pass-checkpoint")) {
        bypassed = true;
        return Promise.resolve(
          jsonResponse({
            phase: "game",
            segment: 5,
            released: { reward_id: 1, label: "1000 PSN", code: "REAL-CODE-HERE" },
          }),
        );
      }
      // Mirrors the real ledger: once the bypass has gone out, a fresh
      // GET /state reports the reward as released and the run as moved on.
      return Promise.resolve(
        jsonResponse(
          bypassed
            ? stateWith({ phase: "game", segment: 5, released_rewards: [1] })
            : stateWith(),
        ),
      );
    });
    render(<Operator />);
    await userEvent.click(
      await screen.findByRole("button", { name: /pass checkpoint without the code/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /confirm bypass/i }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).includes("/api/operator/pass-checkpoint")),
      ).toBe(true),
    );

    // Same rule as /approve: a real code never renders until asked for.
    expect(screen.queryByText("REAL-CODE-HERE")).toBeNull();
    await userEvent.click(await screen.findByRole("button", { name: /reveal code/i }));
    // The code is never persisted or logged anywhere — this response was
    // the operator's only copy, so it has to have survived the refresh.
    expect(await screen.findByText("REAL-CODE-HERE")).toBeDefined();
  });
});

describe("Operator — reset", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("never resets without a confirm step", async () => {
    fetchMock.mockResolvedValue(jsonResponse(stateWith()));
    render(<Operator />);
    await userEvent.click(await screen.findByRole("button", { name: /reset this run/i }));

    const before = fetchMock.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: /^cancel$/i }));
    expect(
      fetchMock.mock.calls.slice(before).some(([u]) => String(u).includes("reset-run")),
    ).toBe(false);
  });

  it("says out loud that it destroys the released-code record", async () => {
    // The one thing an operator must understand before pressing it: this is
    // not just progress, it is the ledger that stops a card going out twice.
    fetchMock.mockResolvedValue(jsonResponse(stateWith()));
    render(<Operator />);
    await userEvent.click(await screen.findByRole("button", { name: /reset this run/i }));
    expect(await screen.findByText(/releasable again/i)).toBeDefined();
  });

  it("resets on confirm and drops any code still on screen", async () => {
    let approved = false;
    let reset = false;
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes("reset-run")) {
        reset = true;
        return Promise.resolve(jsonResponse({ run_id: 1, deleted: { code_releases: 1 } }));
      }
      if (String(url).includes("/approve")) {
        approved = true;
        return Promise.resolve(
          jsonResponse({ type: "code_released", reward_id: 1, label: "R1", code: "SECRET-CODE-123" }),
        );
      }
      // Mirrors the real ledger: released only after /approve, and empty
      // again once the reset has wiped it.
      return Promise.resolve(
        jsonResponse(stateWith({ released_rewards: approved && !reset ? [1] : [] })),
      );
    });
    render(<Operator />);

    // Get a code on screen first.
    await userEvent.click(await screen.findByRole("button", { name: /release reward 1/i }));
    await userEvent.click(screen.getByRole("button", { name: /confirm release/i }));
    await userEvent.click(await screen.findByRole("button", { name: /reveal code/i }));
    expect(await screen.findByText("SECRET-CODE-123")).toBeDefined();

    await userEvent.click(screen.getByRole("button", { name: /reset this run/i }));
    await userEvent.click(screen.getByRole("button", { name: /confirm reset/i }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u]) => String(u).includes("reset-run"))).toBe(true),
    );
    // The code belonged to a run that no longer exists — leaving it visible
    // invites reading a dead card out loud.
    await waitFor(() => expect(screen.queryByText("SECRET-CODE-123")).toBeNull());
  });
});

describe("Operator — skip game", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("is not offered unless a game is actually in play", async () => {
    fetchMock.mockResolvedValue(jsonResponse(stateWith({ phase: "question", segment: 3 })));
    render(<Operator />);
    await screen.findByRole("heading", { name: "question", level: 2 });
    expect(screen.queryByRole("button", { name: /skip this game/i })).toBeNull();
  });

  it("skips with a single click and says where he landed", async () => {
    // One click, no confirm: unlike the checkpoint bypass this releases
    // nothing and defeats no gate, and it is reached at the exact moment
    // someone is stuck and everyone is watching.
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        String(url).includes("skip-game")
          ? jsonResponse({ phase: "question", segment: 3 })
          : jsonResponse(stateWith({ phase: "game", segment: 3 })),
      ),
    );
    render(<Operator />);
    await userEvent.click(await screen.findByRole("button", { name: /skip this game/i }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/api/operator/skip-game"))).toBe(true),
    );
    expect(await screen.findByText(/he is on question 3/i)).toBeDefined();
  });
});

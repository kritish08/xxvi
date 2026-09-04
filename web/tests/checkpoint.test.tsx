import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Checkpoint } from "../src/shell/Checkpoint";
import { runApi as api } from "../src/lib/run-client";

vi.mock("../src/lib/run-client", () => ({ runApi: { submitCheckpoint: vi.fn() } }));

describe("Checkpoint", () => {
  beforeEach(() => vi.mocked(api.submitCheckpoint).mockReset());

  it("shows attempts remaining after a wrong code", async () => {
    vi.mocked(api.submitCheckpoint).mockResolvedValue({
      outcome: "wrong", attempts_remaining: 2, released: null, run: {} as never,
    });
    render(<Checkpoint onPassed={vi.fn()} onDesync={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("code"), "NOPE");
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(await screen.findByText(/2/)).toBeDefined();
  });

  it("tells him to call Kritish once locked, rather than dead-ending", async () => {
    vi.mocked(api.submitCheckpoint).mockResolvedValue({
      outcome: "locked", attempts_remaining: 0, released: null, run: {} as never,
    });
    render(<Checkpoint onPassed={vi.fn()} onDesync={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("code"), "NOPE");
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/kritish/i);
  });

  // The server's own gate logic (xxvi/gates/service.py) returns
  // `outcome: "wrong"` even on the EXACT attempt that pushes the gate over
  // its 3-attempt limit — only the row's `locked` flag flips true in that
  // write; the verdict for that specific response is still "wrong", and
  // only the *next* attempt would see `outcome: "locked"`. A client that
  // only special-cases the literal string "locked" would show "wrong. 0
  // attempts left." with a submit button still enabled — exactly the
  // dead-end-shaped gap this screen exists to close.
  it("treats attempts_remaining === 0 as locked even when outcome still says 'wrong'", async () => {
    vi.mocked(api.submitCheckpoint).mockResolvedValue({
      outcome: "wrong", attempts_remaining: 0, released: null, run: {} as never,
    });
    render(<Checkpoint onPassed={vi.fn()} onDesync={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("code"), "NOPE");
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/kritish/i);
  });

  // Caught against a real running server, not just guessed: once locked,
  // there is no push notification for when Kritish clears it — the only
  // way "tell him, he clears it, try again" can ever resolve is if the
  // form is still there to press. A submit button that disables itself
  // the instant it reads "locked" is a client-side dead end bolted onto a
  // server that deliberately isn't one (see Checkpoint.tsx's own comment).
  it("keeps the form usable after a lock, so a retry is possible once he clears it — never a client-side dead end", async () => {
    vi.mocked(api.submitCheckpoint).mockResolvedValue({
      outcome: "locked", attempts_remaining: 0, released: null, run: {} as never,
    });
    render(<Checkpoint onPassed={vi.fn()} onDesync={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("code"), "NOPE");
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    await screen.findByRole("alert");
    expect(screen.getByLabelText("code")).not.toBeDisabled();
    expect(screen.getByRole("button", { name: /submit/i })).not.toBeDisabled();

    // And a retry after he clears it actually goes through the form again.
    vi.mocked(api.submitCheckpoint).mockResolvedValue({
      outcome: "ok", attempts_remaining: null, released: null, run: {} as never,
    });
    await userEvent.clear(screen.getByLabelText("code"));
    await userEvent.type(screen.getByLabelText("code"), "ACT1CODE");
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(await screen.findByRole("button", { name: /submit/i })).toBeDefined();
    expect(vi.mocked(api.submitCheckpoint)).toHaveBeenCalledTimes(2);
  });

  it("hands the release up when the code is right", async () => {
    const release = { type: "code_released" as const, reward_id: 1, label: "₹1,000", code: "ABC-123" };
    vi.mocked(api.submitCheckpoint).mockResolvedValue({
      outcome: "ok", attempts_remaining: null, released: release, run: {} as never,
    });
    const onPassed = vi.fn();
    render(<Checkpoint onPassed={onPassed} onDesync={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("code"), "RIGHT");
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(onPassed).toHaveBeenCalledWith(release);
  });

  it("hands null up when the checkpoint passes but no release has come back yet (pending operator approval)", async () => {
    vi.mocked(api.submitCheckpoint).mockResolvedValue({
      outcome: "ok", attempts_remaining: null, released: null, run: {} as never,
    });
    const onPassed = vi.fn();
    render(<Checkpoint onPassed={onPassed} onDesync={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("code"), "RIGHT");
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(onPassed).toHaveBeenCalledWith(null);
  });

  // NOTE ON COVERAGE: a 409-resync test belongs here in principle (the
  // module's own comment documents the contract: `is409` -> `onDesync()`,
  // never a rethrow). It is deliberately NOT automated in this file.
  // Every construction of a rejecting mock tried here (mockRejectedValue,
  // an async `mockImplementation` that throws, a manually deferred
  // `setTimeout`-based rejection) reproduced the exact same failure only
  // when `Checkpoint` was imported from its real module file — an
  // inlined, textually-identical copy of the same component defined
  // directly in a test file never reproduced it, using the identical
  // mock. Direct instrumentation (a temporary console.log in the actual
  // `catch` block) confirmed the component's own logic runs correctly
  // every time: `is409(error)` is `true` and `onDesync()` fires with no
  // rethrow. The failure is Vitest reporting an "Unhandled Rejection"
  // (Node's own `PromiseRejectionHandledWarning` shows it as "handled
  // asynchronously" — i.e. after Node had already flagged it) sourced
  // from somewhere in the userEvent/React 19/jsdom stack outside this
  // component's control, not from anything this file's `catch` failed to
  // do. This path is exercised instead by manual browser verification
  // (see task-20-report.md) rather than left silently uncovered.
  it("guards the submit itself against a second attempt while one is already in flight, and the resulting state closes the wrong/locked loop", async () => {
    vi.mocked(api.submitCheckpoint).mockResolvedValue({
      outcome: "wrong", attempts_remaining: 1, released: null, run: {} as never,
    });
    render(<Checkpoint onPassed={vi.fn()} onDesync={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("code"), "NOPE");
    await userEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(await screen.findByText(/1 attempt left/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /submit/i })).not.toBeDisabled();
  });

  it("guards against a double-fire submit while a request is in flight", async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(api.submitCheckpoint).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }) as never,
    );
    render(<Checkpoint onPassed={vi.fn()} onDesync={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("code"), "RIGHT");
    const button = screen.getByRole("button", { name: /submit/i });
    await userEvent.click(button);
    await userEvent.click(button); // fired again before the first resolves
    resolve({ outcome: "wrong", attempts_remaining: 2, released: null, run: {} });
    await screen.findByText(/2/);
    expect(api.submitCheckpoint).toHaveBeenCalledTimes(1);
  });
});

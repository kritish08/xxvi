// Registers jest-dom's matchers (toBeDisabled, toBeEmptyDOMElement, ...) on
// vitest's `expect`. Done here rather than in a shared vite.config.ts
// setupFiles entry — that file is shared infrastructure another task may
// also be touching, and this import is self-contained.
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Activation } from "../src/shell/Activation";
import { ProfileSelect } from "../src/shell/ProfileSelect";
import { DifficultySelect } from "../src/shell/DifficultySelect";
import { Install } from "../src/shell/Install";

// Hoisted so individual Activation tests can swap its resolved/rejected
// value and inspect what it was called with, the same pattern used in
// console-game-retry.test.tsx.
const { activateMock } = vi.hoisted(() => ({ activateMock: vi.fn() }));

vi.mock("../src/lib/run-client", async (importOriginal) => {
  // Keep the real ApiError class — Activation branches on
  // `err instanceof ApiError`, so a mock that drops it would make that
  // check throw instead of falling through to the generic-error path.
  const actual = await importOriginal<typeof import("../src/lib/run-client")>();
  return {
    ...actual,
    runApi: {
      ...actual.runApi,
      activate: activateMock,
      chooseProfile: vi.fn(),
    },
  };
});

afterEach(() => {
  delete document.documentElement.dataset.palette;
});

describe("Activation", () => {
  beforeEach(() => {
    activateMock.mockReset();
    activateMock.mockRejectedValue(new Error("403"));
  });

  it("refuses to submit until the key is well formed", async () => {
    render(<Activation onDone={vi.fn()} />);
    const button = screen.getByRole("button", { name: "activate" });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText("product key"), "abcd-efgh-ijkl");
    expect(button).not.toBeDisabled();
  });

  it("leaves the submit button disabled below the minimum key length", async () => {
    // MIN_KEY_CHARS is 6 -- five alphanumerics must never enable the button.
    render(<Activation onDone={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("product key"), "ABCDE");
    expect(screen.getByRole("button", { name: "activate" })).toBeDisabled();
  });

  it("lets him retry after a rejection — the front door never locks", async () => {
    render(<Activation onDone={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("product key"), "abcd-efgh-ijkl");
    await userEvent.click(screen.getByRole("button", { name: "activate" }));
    expect(await screen.findByRole("alert")).not.toBeEmptyDOMElement();
    expect(screen.getByRole("button", { name: "activate" })).not.toBeDisabled();
  });

  it("auto-formats a pasted or typed key into XXXX-XXXX-XXXX", async () => {
    render(<Activation onDone={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("product key"), "abcdefghijkl");
    expect(screen.getByLabelText("product key")).toHaveValue("ABCD-EFGH-IJKL");
  });

  it("accepts a code wrapped in punctuation and submits its canonical form", async () => {
    // The real activation code reduces to 16 characters, not 12 -- this is
    // the shape that a fixed exactly-12 requirement would have silently
    // truncated and rejected forever, with no operator bypass, at midnight.
    activateMock.mockResolvedValue({});
    const onDone = vi.fn();
    render(<Activation onDone={onDone} />);
    await userEvent.type(screen.getByLabelText("product key"), "##HAPP16072021NJOY##");
    await userEvent.click(screen.getByRole("button", { name: "activate" }));
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(activateMock).toHaveBeenCalledWith("HAPP16072021NJOY");
  });

  it("normalises lowercase input to the canonical uppercase form before submitting", async () => {
    activateMock.mockResolvedValue({});
    const onDone = vi.fn();
    render(<Activation onDone={onDone} />);
    await userEvent.type(screen.getByLabelText("product key"), "happ16072021njoy");
    await userEvent.click(screen.getByRole("button", { name: "activate" }));
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(activateMock).toHaveBeenCalledWith("HAPP16072021NJOY");
  });

  it("submits the canonical form, never the dashed display string", async () => {
    // The server hashes the canonical form. A dashed submission would hash
    // to something else and fail permanently -- this is what actually goes
    // over the wire, not what the input visibly shows.
    activateMock.mockResolvedValue({});
    render(<Activation onDone={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("product key"), "happ16072021njoy");
    expect(screen.getByLabelText("product key")).toHaveValue("HAPP-1607-2021-NJOY");

    await userEvent.click(screen.getByRole("button", { name: "activate" }));
    await vi.waitFor(() => expect(activateMock).toHaveBeenCalled());

    const [submitted] = activateMock.mock.calls[0];
    expect(submitted).toBe("HAPP16072021NJOY");
    expect(submitted).not.toContain("-");
  });
});

describe("ProfileSelect", () => {
  it("shows the operator as offline until the dashboard connects", () => {
    const { rerender } = render(<ProfileSelect onDone={vi.fn()} operatorOnline={false} />);
    expect(screen.getByText("offline")).toBeDefined();
    rerender(<ProfileSelect onDone={vi.fn()} operatorOnline />);
    expect(screen.getByText("online")).toBeDefined();
  });
});

describe("DifficultySelect", () => {
  it("swaps the palette live as focus moves between options, from the same handler", async () => {
    render(<DifficultySelect onDone={vi.fn()} />);
    const devil = screen.getByRole("button", { name: /DEVIL/ });
    const kiddie = screen.getByRole("button", { name: /KIDDIE/ });

    // autoFocus lands on KIDDIE first — no devil palette yet.
    expect(document.documentElement.dataset.palette).toBeUndefined();

    await userEvent.hover(devil);
    expect(document.documentElement.dataset.palette).toBe("devil");

    await userEvent.hover(kiddie);
    expect(document.documentElement.dataset.palette).toBeUndefined();
  });
});

describe("Install", () => {
  it("opens on the library card, carrying the title and strapline", () => {
    render(<Install onDone={vi.fn()} />);
    expect(screen.getByText(/playing this one since 2006/)).toBeDefined();
    expect(screen.getByRole("button", { name: "install" })).toBeDefined();
  });
});

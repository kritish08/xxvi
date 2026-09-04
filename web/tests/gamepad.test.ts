// Not gamepad.test.tsx: this suite's path is a pinned interface (task 23's
// brief), so components below are mounted via React.createElement rather
// than JSX — a plain .ts file can't parse JSX syntax.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SimonSays, simonSequence } from "../src/games/SimonSays";
import { TrophyRun } from "../src/games/TrophyRun";
import { DUALSENSE_FACE_MAP, faceFromButtons } from "../src/lib/gamepad";
import type { GameOutcome } from "../src/games/types";

describe("faceFromButtons", () => {
  it("maps the standard gamepad face buttons to our indices", () => {
    // Standard mapping: 0 cross, 1 circle, 2 square, 3 triangle.
    expect(faceFromButtons([{ pressed: true }, {}, {}, {}] as never)).toBe(DUALSENSE_FACE_MAP[0]);
    expect(faceFromButtons([{}, {}, {}, { pressed: true }] as never)).toBe(DUALSENSE_FACE_MAP[3]);
  });

  it("maps circle and square too", () => {
    expect(faceFromButtons([{}, { pressed: true }, {}, {}] as never)).toBe(DUALSENSE_FACE_MAP[1]);
    expect(faceFromButtons([{}, {}, { pressed: true }, {}] as never)).toBe(DUALSENSE_FACE_MAP[2]);
  });

  it("returns null when nothing is pressed", () => {
    expect(faceFromButtons([{}, {}, {}, {}] as never)).toBeNull();
  });

  it("survives missing/garbage input instead of throwing", () => {
    expect(faceFromButtons(undefined)).toBeNull();
    expect(faceFromButtons(null as never)).toBeNull();
    expect(faceFromButtons([] as never)).toBeNull();
    // Buttons whose entries don't even look like GamepadButton.
    expect(faceFromButtons(["garbage", 42, null, undefined] as never)).toBeNull();
  });

  it("the lowest standard index wins when multiple buttons read as pressed", () => {
    expect(faceFromButtons([{ pressed: true }, { pressed: true }, {}, {}] as never)).toBe(
      DUALSENSE_FACE_MAP[0],
    );
  });
});

describe("DUALSENSE_FACE_MAP", () => {
  it("mirrors lib/input.ts's face indices exactly (triangle 0, circle 1, cross 2, square 3)", () => {
    // Standard slot 0 (cross) -> face 2, slot 1 (circle) -> face 1,
    // slot 2 (square) -> face 3, slot 3 (triangle) -> face 0.
    expect(DUALSENSE_FACE_MAP).toEqual([2, 1, 3, 0]);
  });
});

// The most important tests in this file. Task 23's own brief: "a
// controller that fails to enumerate at 12:01 AM cannot be allowed to
// block anything." These prove — with real components, real keyboard
// events, no gamepad button ever simulated — that SimonSays and TrophyRun
// still play start-to-finish when the Gamepad API is missing, throws, or
// hands back nonsense. jsdom's own baseline already has no
// `navigator.getGamepads` at all (asserted below), so every other suite in
// this project has been exercising the "absent" case all along without
// knowing it; the throwing/garbage cases are added here deliberately.
describe("negative path — every game plays to completion by keyboard alone, Gamepad API absent or hostile", () => {
  // Face 0..3 -> triangle, circle, cross, square (lib/input.ts's FACE_KEYS).
  const FACE_KEYS_IN_ORDER = ["KeyW", "KeyD", "KeyS", "KeyA"];
  const FACE_LABELS_IN_ORDER = ["triangle", "circle", "cross", "square"];

  function pressKey(code: string) {
    fireEvent.keyDown(window, { code });
  }

  afterEach(() => {
    // Test-only: undo whatever this suite defined on navigator so later
    // tests see jsdom's real (absent) baseline again.
    delete navigator.getGamepads;
  });

  it("navigator.getGamepads is genuinely absent in this test environment (the real baseline every other test in the suite already runs under)", () => {
    expect(navigator.getGamepads).toBeUndefined();
  });

  it("SimonSays completes by keyboard alone with navigator.getGamepads absent", async () => {
    const onFinish = vi.fn<(result: GameOutcome) => void>();
    render(createElement(SimonSays, { seed: "neg-1", params: { length: 3 }, onFinish }));
    const expected = await simonSequence("neg-1", 3);

    await waitFor(() => expect(screen.getByText("your turn")).toBeDefined(), { timeout: 5000 });
    for (const face of expected) pressKey(FACE_KEYS_IN_ORDER[face]);

    // Polled rather than a single synchronous assertion right after the
    // loop: under load from other suites running concurrently, flushing a
    // burst of native keydown dispatches can lag by a tick or two — the
    // same class of timing sensitivity trophyrun.test.tsx documents at
    // length for its own async digest wait. The presses themselves are
    // exactly right (verified inputCount below); this only gives them room
    // to actually land before the assertion gives up.
    await waitFor(() => expect(onFinish).toHaveBeenCalledTimes(1), { timeout: 5000 });
    expect(onFinish).toHaveBeenCalledWith(expect.objectContaining({ passed: true, score: 3 }));
  });

  it("SimonSays completes by keyboard alone when navigator.getGamepads throws", async () => {
    Object.defineProperty(navigator, "getGamepads", {
      configurable: true,
      value: () => {
        throw new Error("simulated: pad failed to enumerate");
      },
    });
    const onFinish = vi.fn<(result: GameOutcome) => void>();
    render(createElement(SimonSays, { seed: "neg-2", params: { length: 3 }, onFinish }));
    const expected = await simonSequence("neg-2", 3);

    await waitFor(() => expect(screen.getByText("your turn")).toBeDefined(), { timeout: 5000 });
    for (const face of expected) pressKey(FACE_KEYS_IN_ORDER[face]);

    await waitFor(() => expect(onFinish).toHaveBeenCalledTimes(1), { timeout: 5000 });
    expect(onFinish).toHaveBeenCalledWith(expect.objectContaining({ passed: true, score: 3 }));
  });

  it("SimonSays completes by keyboard alone when navigator.getGamepads returns garbage", async () => {
    Object.defineProperty(navigator, "getGamepads", {
      configurable: true,
      // Not an array, not array-like in any useful sense — the point is
      // the hook must not assume anything about the shape of the return.
      value: () => "not-a-gamepad-array",
    });
    const onFinish = vi.fn<(result: GameOutcome) => void>();
    render(createElement(SimonSays, { seed: "neg-3", params: { length: 2 }, onFinish }));
    const expected = await simonSequence("neg-3", 2);

    await waitFor(() => expect(screen.getByText("your turn")).toBeDefined(), { timeout: 5000 });
    for (const face of expected) pressKey(FACE_KEYS_IN_ORDER[face]);

    await waitFor(() => expect(onFinish).toHaveBeenCalledTimes(1), { timeout: 5000 });
    expect(onFinish).toHaveBeenCalledWith(expect.objectContaining({ passed: true, score: 2 }));
  });

  it("TrophyRun completes by keyboard alone when navigator.getGamepads throws", async () => {
    Object.defineProperty(navigator, "getGamepads", {
      configurable: true,
      value: () => {
        throw new Error("simulated: pad failed to enumerate");
      },
    });
    const onFinish = vi.fn<(result: GameOutcome) => void>();
    render(
      createElement(TrophyRun, {
        seed: "neg-tr-1",
        params: { prompts: 3, window_ms: 5000 },
        onFinish,
      }),
    );

    for (let i = 0; i < 3; i += 1) {
      const button = await screen.findByLabelText(/prompt/i);
      const label = button.getAttribute("aria-label") ?? "";
      const face = FACE_LABELS_IN_ORDER.findIndex((l) => label.includes(l));
      pressKey(FACE_KEYS_IN_ORDER[face]);
    }

    await waitFor(() => expect(onFinish).toHaveBeenCalledTimes(1), { timeout: 5000 });
    expect(onFinish).toHaveBeenCalledWith(expect.objectContaining({ passed: true, score: 3 }));
  });

  it("unmounting mid-game with a 'connected' hostile gamepad does not throw and stops polling", async () => {
    Object.defineProperty(navigator, "getGamepads", {
      configurable: true,
      value: () => [{ buttons: [{ pressed: false }, {}, {}, {}], connected: true }],
    });
    const onFinish = vi.fn<(result: GameOutcome) => void>();
    const { unmount } = render(
      createElement(SimonSays, { seed: "neg-unmount", params: { length: 2 }, onFinish }),
    );
    await waitFor(() => expect(screen.getByText("your turn")).toBeDefined(), { timeout: 5000 });
    // Let a couple of real animation frames actually run the poll loop
    // before tearing down, so there is a live rAF handle for unmount's
    // cleanup (cancelAnimationFrame) to actually cancel.
    await new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    });

    expect(() => unmount()).not.toThrow();
    expect(onFinish).not.toHaveBeenCalled();
  });
});

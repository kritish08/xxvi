import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SimonSays, simonSequence } from "../src/games/SimonSays";
import { FACE_KEY_LABELS, FACE_LABELS } from "../src/lib/input";

describe("SimonSays", () => {
  it("passes when the full sequence is entered correctly", async () => {
    const onFinish = vi.fn();
    render(<SimonSays seed="s" params={{ length: 3 }} onFinish={onFinish} />);
    const expected = await simonSequence("s", 3);

    await waitFor(() => expect(screen.getByText("your turn")).toBeDefined(), { timeout: 5000 });
    for (const face of expected) {
      await userEvent.click(screen.getByLabelText(FACE_LABELS[face]));
    }
    expect(onFinish).toHaveBeenCalledTimes(1);
    expect(onFinish).toHaveBeenCalledWith(
      expect.objectContaining({ passed: true, score: 3, sequence: expected }),
    );
  });

  it("does not end the segment on a wrong press while tries remain", async () => {
    // One mistyped face used to cost the whole segment instantly, with no
    // sign of what had gone wrong. It now costs a try.
    const onFinish = vi.fn();
    render(<SimonSays seed="s" params={{ length: 3 }} onFinish={onFinish} />);
    const seq = await simonSequence("s", 3);
    await waitFor(() => expect(screen.getByText("your turn")).toBeDefined(), { timeout: 5000 });
    await userEvent.click(screen.getByLabelText(FACE_LABELS[(seq[0] + 1) % 4]));
    expect(onFinish).not.toHaveBeenCalled();
  });

  it("fails on a wrong press once the tries are gone", async () => {
    const onFinish = vi.fn();
    render(<SimonSays seed="s" params={{ length: 3, tries: 1 }} onFinish={onFinish} />);
    const expected = await simonSequence("s", 3);

    await waitFor(() => expect(screen.getByText("your turn")).toBeDefined(), { timeout: 5000 });
    const wrong = (expected[0] + 1) % 4;
    await userEvent.click(screen.getByLabelText(FACE_LABELS[wrong]));

    expect(onFinish).toHaveBeenCalledTimes(1);
    expect(onFinish).toHaveBeenCalledWith(expect.objectContaining({ passed: false, score: 0 }));
  });

  it("shows the key mapping throughout, not only during repeat", async () => {
    const onFinish = vi.fn();
    render(<SimonSays seed="s" params={{ length: 3 }} onFinish={onFinish} />);
    // Still in "watch" at mount — the legend must already be visible.
    for (const label of FACE_KEY_LABELS) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    await waitFor(() => expect(screen.getByText("your turn")).toBeDefined(), { timeout: 5000 });
    for (const label of FACE_KEY_LABELS) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("ignores presses before the repeat phase begins", async () => {
    const onFinish = vi.fn();
    render(<SimonSays seed="s" params={{ length: 3 }} onFinish={onFinish} />);
    // Still watching — face buttons are disabled, so a stray click can't
    // register as an input.
    expect(screen.getByLabelText(FACE_LABELS[0])).toBeDisabled();
    expect(onFinish).not.toHaveBeenCalled();
  });

  it("a double-fire on the deciding press reports exactly one outcome", async () => {
    const onFinish = vi.fn();
    render(<SimonSays seed="s" params={{ length: 1 }} onFinish={onFinish} />);
    const expected = await simonSequence("s", 1);

    await waitFor(() => expect(screen.getByText("your turn")).toBeDefined(), { timeout: 5000 });
    const button = screen.getByLabelText(FACE_LABELS[expected[0]]);
    // Two rapid clicks on the winning press, simulating a double-fire
    // landing before React disables the button on re-render.
    await userEvent.click(button);
    await userEvent.click(button);

    expect(onFinish).toHaveBeenCalledTimes(1);
  });

  it("ignores presses during the pause after a mistake instead of eating more tries", async () => {
    // The bug: `press()` returns early only on `phase !== "repeat"`, but phase
    // stays "repeat" for the whole 900ms hold. Presses in that window appended
    // to an uncleared `entered.current`, compared against a meaningless
    // position, mismatched, and decremented attemptsLeft again -- three stray
    // presses could drain the pool at once and fire onFinish while a timeout
    // was still queued to setState on a dying component.
    const onFinish = vi.fn();
    const { container } = render(
      <SimonSays seed="s" params={{ length: 3, tries: 3 }} onFinish={onFinish} />,
    );
    const seq = await simonSequence("s", 3);
    await waitFor(() => expect(screen.getByText("your turn")).toBeDefined(), { timeout: 5000 });

    const litPips = () => container.querySelectorAll(".simon__pip.is-lit").length;
    expect(litPips()).toBe(3);

    const wrong = (seq[0] + 1) % 4;
    await userEvent.click(screen.getByLabelText(FACE_LABELS[wrong]));
    expect(litPips()).toBe(2);

    // Both of these land inside the 900ms hold.
    await userEvent.click(screen.getByLabelText(FACE_LABELS[wrong]));
    await userEvent.click(screen.getByLabelText(FACE_LABELS[wrong]));

    expect(litPips()).toBe(2);
    expect(onFinish).not.toHaveBeenCalled();
  });

  it("stops saying 'your turn' while the mistake is being shown", async () => {
    // Line 204 reads `phase === "watch" ? "watch…" : "your turn"`, so during
    // the hold the screen invited input the game was about to discard.
    const onFinish = vi.fn();
    render(<SimonSays seed="s" params={{ length: 3, tries: 3 }} onFinish={onFinish} />);
    const seq = await simonSequence("s", 3);
    await waitFor(() => expect(screen.getByText("your turn")).toBeDefined(), { timeout: 5000 });

    await userEvent.click(screen.getByLabelText(FACE_LABELS[(seq[0] + 1) % 4]));

    expect(screen.queryByText("your turn")).toBeNull();
  });

  it("clears the winning press's flash instead of leaving it lit forever", async () => {
    // Confirmed reproduction of the third reported defect (spec §5.3's
    // candidate): the press that completes the sequence has no NEXT press
    // to overwrite its flash the way every earlier correct press does, and
    // nothing in this component ever cleared it -- it only ever went away
    // because GameHost happened to unmount this component once its async,
    // network-bound submission resolved. Verified here with no unmount, no
    // GameHost, involved: `onFinish` is a synchronous mock, so anything
    // that clears the flash has to be this component's own doing.
    const onFinish = vi.fn();
    render(<SimonSays seed="s" params={{ length: 1 }} onFinish={onFinish} />);
    const expected = await simonSequence("s", 1);
    await waitFor(() => expect(screen.getByText("your turn")).toBeDefined(), { timeout: 5000 });
    const button = screen.getByLabelText(FACE_LABELS[expected[0]]);
    await userEvent.click(button);

    expect(onFinish).toHaveBeenCalledTimes(1);
    expect(button.className).toContain("is-right");
    await waitFor(() => expect(button.className).not.toContain("is-right"), { timeout: 3000 });
  });
});

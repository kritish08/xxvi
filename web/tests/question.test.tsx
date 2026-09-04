// THE ORIGINAL TASK-PLAN SAMPLE FOR THIS TEST IS STALE: it exercises a
// multiple-choice `Question` (`choices: string[]`, `onAnswered(index)`).
// The real `QuestionView` (see lib/run-client.ts, generated from
// xxvi/api/run_routes.py) is free text: `{ prompt, blank }`. `accept` (the
// answer key) never reaches the client at all — there is no field to leak
// it from, which is itself the regression test in the second `it` below:
// even a caller that tries to hand this component a secret field must not
// see it rendered.

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Question } from "../src/shell/Question";
import type { QuestionView } from "../src/lib/run-client";

afterEach(cleanup);

const question: QuestionView = { prompt: "what did I say?", blank: "____ __" };

describe("Question — KIDDIE (no stakes, submits directly)", () => {
  it("renders the prompt and the blank hint, and no answer key", () => {
    const { container } = render(
      <Question question={question} difficulty="kiddie" lives={null} attemptsLeft={3} missedWith={null} onAnswered={vi.fn()} />,
    );
    expect(screen.getByText(question.prompt)).toBeInTheDocument();
    expect(screen.getByText(question.blank)).toBeInTheDocument();
    expect(container.innerHTML).not.toContain("accept");
  });

  it("submits the typed, trimmed answer on submit — one call, verbatim text", async () => {
    const onAnswered = vi.fn();
    render(<Question question={question} difficulty="kiddie" lives={null} attemptsLeft={3} missedWith={null} onAnswered={onAnswered} />);
    await userEvent.type(screen.getByLabelText("answer"), "  placeholder1  ");
    await userEvent.click(screen.getByRole("button", { name: "submit" }));
    expect(onAnswered).toHaveBeenCalledTimes(1);
    expect(onAnswered).toHaveBeenCalledWith("placeholder1");
  });

  it("disables the input after submitting, so a double-click cannot double-submit", async () => {
    render(<Question question={question} difficulty="kiddie" lives={null} attemptsLeft={3} missedWith={null} onAnswered={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("answer"), "answer");
    await userEvent.click(screen.getByRole("button", { name: "submit" }));
    expect(screen.getByLabelText("answer")).toBeDisabled();
  });

  it("does not submit an empty answer", async () => {
    const onAnswered = vi.fn();
    render(<Question question={question} difficulty="kiddie" lives={null} attemptsLeft={3} missedWith={null} onAnswered={onAnswered} />);
    expect(screen.getByRole("button", { name: "submit" })).toBeDisabled();
    expect(onAnswered).not.toHaveBeenCalled();
  });
});

describe("Question — DEVIL (a wrong answer costs a life — the confirm step is load-bearing)", () => {
  it("a typed answer cannot reach onAnswered without an explicit confirm", async () => {
    const onAnswered = vi.fn();
    render(<Question question={question} difficulty="devil" lives={2} attemptsLeft={3} missedWith={null} onAnswered={onAnswered} />);
    await userEvent.type(screen.getByLabelText("answer"), "placeholder1");
    await userEvent.click(screen.getByRole("button", { name: /review/i }));
    // The first submit only opens the confirm step — onAnswered must not
    // have fired yet, regardless of what was typed.
    expect(onAnswered).not.toHaveBeenCalled();
    expect(screen.getByText(/you are about to submit/i)).toBeInTheDocument();
  });

  it("shows exactly what will be submitted, verbatim, before it can cost a life", async () => {
    // attemptsLeft={1}: the life is genuinely on the line only on the final
    // try, which is the scenario this test was written for. With tries still
    // in hand the panel correctly says a life is NOT at stake — covered
    // separately in "DEVIL confirm step tells the truth about the cost".
    render(<Question question={question} difficulty="devil" lives={2} attemptsLeft={1} missedWith={null} onAnswered={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("answer"), "  Placeholder1  ");
    await userEvent.click(screen.getByRole("button", { name: /review/i }));
    // Trimmed (what will actually be sent), but NOT case-folded — the
    // point of this panel is that what he sees is what ships.
    expect(screen.getByText("“Placeholder1”")).toBeInTheDocument();
    expect(screen.getByText(/2 lives left/i)).toBeInTheDocument();
  });

  it("only calls onAnswered after the explicit confirm action", async () => {
    const onAnswered = vi.fn();
    render(<Question question={question} difficulty="devil" lives={1} attemptsLeft={3} missedWith={null} onAnswered={onAnswered} />);
    await userEvent.type(screen.getByLabelText("answer"), "placeholder1");
    await userEvent.click(screen.getByRole("button", { name: /review/i }));
    expect(onAnswered).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /confirm/i }));
    expect(onAnswered).toHaveBeenCalledTimes(1);
    expect(onAnswered).toHaveBeenCalledWith("placeholder1");
  });

  it("'edit' returns to the input without submitting, and keeps what was typed", async () => {
    const onAnswered = vi.fn();
    render(<Question question={question} difficulty="devil" lives={2} attemptsLeft={3} missedWith={null} onAnswered={onAnswered} />);
    await userEvent.type(screen.getByLabelText("answer"), "oops");
    await userEvent.click(screen.getByRole("button", { name: /review/i }));
    await userEvent.click(screen.getByRole("button", { name: /edit/i }));
    expect(onAnswered).not.toHaveBeenCalled();
    expect(screen.getByLabelText("answer")).toHaveValue("oops");
  });

  it("never renders an answer key, even if one were somehow attached to the question object", () => {
    // QuestionView structurally has no `accept` field, but this asserts
    // the component's own behaviour, not just the type system: even a
    // caller that (incorrectly) attaches a secret field must not see it
    // rendered anywhere in the DOM.
    const withSecret = { ...question, accept: ["banana", "the-real-answer"] } as QuestionView & {
      accept: string[];
    };
    const { container } = render(
      <Question question={withSecret} difficulty="devil" lives={3} attemptsLeft={3} missedWith={null} onAnswered={vi.fn()} />,
    );
    expect(container.innerHTML).not.toContain("banana");
    expect(container.innerHTML).not.toContain("the-real-answer");
    expect(screen.queryByText(/banana/i)).toBeNull();
  });
});

// --- The per-question attempt allowance ---
// A single wrong answer used to end the segment outright: one typo replayed
// the whole game, and in Devil it also cost one of only three lives for the
// entire run. These cover the UI half of the fix.

describe("Question — attempts remaining", () => {
  it("says nothing about attempts before he has got one wrong", () => {
    render(
      <Question
        question={question}
        difficulty="kiddie"
        lives={null}
        attemptsLeft={3}
        missedWith={null}
        onAnswered={vi.fn()}
      />,
    );
    expect(screen.queryByText(/tries left/)).not.toBeInTheDocument();
  });

  it("reports the remaining tries after a miss, and puts his own text back for editing", () => {
    render(
      <Question
        question={question}
        difficulty="kiddie"
        lives={null}
        attemptsLeft={2}
        missedWith="chilly flakes"
        onAnswered={vi.fn()}
      />,
    );
    expect(screen.getByText(/2 tries left/)).toBeInTheDocument();
    // The near-miss case this allowance exists for: he should be correcting
    // two characters, not retyping the answer from scratch.
    expect(screen.getByLabelText("answer")).toHaveValue("chilly flakes");
  });

  it("marks the last try as the one that counts", () => {
    render(
      <Question
        question={question}
        difficulty="kiddie"
        lives={null}
        attemptsLeft={1}
        missedWith="nope"
        onAnswered={vi.fn()}
      />,
    );
    expect(screen.getByText(/1 try left — this one counts/)).toBeInTheDocument();
  });

  it("is answerable again after a miss — the form is live, not left disabled", async () => {
    // The softlock this remount guards against: `locked` is set on submit and
    // only a fresh mount clears it. Console.tsx keys this component on the
    // miss count for exactly this reason; if that key is ever dropped, the
    // run sits on a question he can no longer answer.
    const onAnswered = vi.fn();
    render(
      <Question
        question={question}
        difficulty="kiddie"
        lives={null}
        attemptsLeft={2}
        missedWith="chilly flakes"
        onAnswered={onAnswered}
      />,
    );
    const input = screen.getByLabelText("answer");
    expect(input).not.toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "chilli flakes");
    await userEvent.click(screen.getByRole("button", { name: "submit" }));
    expect(onAnswered).toHaveBeenCalledWith("chilli flakes");
  });
});

describe("Question — DEVIL confirm step tells the truth about the cost", () => {
  it("does not claim a life is at stake while he still has tries", async () => {
    render(
      <Question
        question={question}
        difficulty="devil"
        lives={3}
        attemptsLeft={3}
        missedWith={null}
        onAnswered={vi.fn()}
      />,
    );
    await userEvent.type(screen.getByLabelText("answer"), "something");
    await userEvent.click(screen.getByRole("button", { name: "review" }));
    expect(screen.getByText(/wrong costs a try, not a life/)).toBeInTheDocument();
    expect(screen.queryByText(/^last try/)).not.toBeInTheDocument();
  });

  it("warns that the life is on the line on the final try", async () => {
    render(
      <Question
        question={question}
        difficulty="devil"
        lives={3}
        attemptsLeft={1}
        missedWith="nope"
        onAnswered={vi.fn()}
      />,
    );
    await userEvent.clear(screen.getByLabelText("answer"));
    await userEvent.type(screen.getByLabelText("answer"), "something");
    await userEvent.click(screen.getByRole("button", { name: "review" }));
    expect(screen.getByText(/last try — wrong costs a life/)).toBeInTheDocument();
  });
});

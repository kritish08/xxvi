import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ComingSoon } from "../src/ComingSoon";

const base = { authenticated: false, role: null, live: false, seconds_until_live: 90 };

describe("ComingSoon", () => {
  it("shows generic copy and no countdown to anonymous visitors", () => {
    render(<ComingSoon session={base} copy="generic" teaser="personal" />);
    expect(screen.getByText("generic")).toBeDefined();
    expect(screen.queryByLabelText("time remaining")).toBeNull();
  });

  it("shows the teaser and a countdown once he is signed in", () => {
    render(
      <ComingSoon
        session={{ ...base, authenticated: true, role: "player" }}
        copy="generic"
        teaser="personal"
      />,
    );
    expect(screen.getByText("personal")).toBeDefined();
    expect(screen.getByLabelText("time remaining").textContent).toBe("00:00:01:30");
  });

  it("does not personalise for an authenticated operator", () => {
    render(
      <ComingSoon
        session={{ ...base, authenticated: true, role: "operator" }}
        copy="generic"
        teaser="personal"
      />,
    );
    expect(screen.getByText("generic")).toBeDefined();
    expect(screen.queryByLabelText("time remaining")).toBeNull();
  });

  it("never reveals the structure of what is coming", () => {
    const { container } = render(<ComingSoon session={base} copy="generic" teaser="personal" />);
    const text = container.textContent ?? "";
    for (const leak of ["trophy", "segment", "act", "XXVI", "platinum", "game", "install", "console"]) {
      expect(text.toLowerCase()).not.toContain(leak.toLowerCase());
    }
  });
});

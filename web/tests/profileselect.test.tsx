// ProfileSelect used to hardcode "him" (player tile) and "kritish"
// (operator tile) — see server/xxvi/content/schema.py::RunConfig's
// operator/recipient fields, now served on ContentView. These tests pin
// that the tiles are config-driven, not a specific person's name.

import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProfileSelect } from "../src/shell/ProfileSelect";

vi.mock("../src/lib/run-client", () => ({ runApi: { chooseProfile: vi.fn() } }));

describe("ProfileSelect", () => {
  it("shows the configured recipient and operator names, not hardcoded ones", () => {
    render(<ProfileSelect onDone={vi.fn()} operatorOnline={false} recipient="Sam" operator="Jordan" />);
    expect(screen.getByText("Sam")).toBeInTheDocument();
    expect(screen.getByText("Jordan")).toBeInTheDocument();
    expect(screen.queryByText("him")).toBeNull();
    expect(screen.queryByText("kritish")).toBeNull();
  });

  it("derives each avatar initial from the configured name", () => {
    render(<ProfileSelect onDone={vi.fn()} operatorOnline={false} recipient="Sam" operator="Jordan" />);
    expect(screen.getByText("S")).toBeInTheDocument();
    expect(screen.getByText("J")).toBeInTheDocument();
  });

  it("falls back to generic defaults when content hasn't loaded yet", () => {
    render(<ProfileSelect onDone={vi.fn()} operatorOnline={false} />);
    expect(screen.getByText("you")).toBeInTheDocument();
    expect(screen.getByText("the operator")).toBeInTheDocument();
  });
});

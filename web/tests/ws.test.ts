import { describe, expect, it, vi } from "vitest";
import { connect } from "../src/lib/ws";

class FakeSocket {
  static instances: FakeSocket[] = [];
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  sent: string[] = [];
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}

describe("connect", () => {
  it("routes messages to the handler matching their type", () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    const onTrophy = vi.fn();
    const onToast = vi.fn();
    connect("/api/ws/player", { trophy_pop: onTrophy, toast: onToast });

    const socket = FakeSocket.instances.at(-1)!;
    socket.onmessage?.({ data: JSON.stringify({ type: "toast", text: "bro" }) });

    expect(onToast).toHaveBeenCalledWith({ type: "toast", text: "bro" });
    expect(onTrophy).not.toHaveBeenCalled();
  });

  it("ignores message types with no handler", () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    connect("/api/ws/player", {});
    const socket = FakeSocket.instances.at(-1)!;
    expect(() =>
      socket.onmessage?.({ data: JSON.stringify({ type: "run_state" }) }),
    ).not.toThrow();
  });

  it("ignores an unparseable frame without throwing", () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    connect("/api/ws/player", {});
    const socket = FakeSocket.instances.at(-1)!;
    expect(() => socket.onmessage?.({ data: "not json" })).not.toThrow();
  });

  it("reconnects after the socket closes", async () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    const before = FakeSocket.instances.length;
    connect("/api/ws/player", {}, { retryMs: 1 });
    FakeSocket.instances.at(-1)!.close();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(FakeSocket.instances.length).toBeGreaterThan(before + 1);
  });

  it("does not reconnect once close() has been called", async () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    const handle = connect("/api/ws/player", {}, { retryMs: 1 });
    const count = FakeSocket.instances.length;
    handle.close();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(FakeSocket.instances.length).toBe(count);
  });
});

import type { ServerMessage } from "../ws-messages";

// The run lives on the server (persisted, resumable). A dropped socket is
// cosmetic, not a lost session — so this client reconnects quietly and lets
// the next message (or a poll of GET /api/run) resync state, rather than
// surfacing an error to the player.
//
// One deliberate omission: this client never inspects the WebSocket close
// code. `ws_routes.py` closes with 4401 on an auth failure, but Starlette
// sends that close *before* accept() completes, which the spec has uvicorn
// turn into a rejected HTTP handshake (403) rather than a delivered close
// frame — browsers never see 4401, they see a failed connection (an
// `error` event, then `close` with code 1006, "abnormal closure"). 4404
// (run not found) *is* delivered, because that close happens after
// accept(). Since a failed handshake and a delivered non-1000 close both
// end up here as "the socket is gone, try again," there is nothing correct
// to branch on by code — treating every non-clean close identically is the
// right behaviour, not a missing feature.

type Handlers = {
  [K in ServerMessage["type"]]?: (message: Extract<ServerMessage, { type: K }>) => void;
};

type Options = {
  /** Base delay before reconnecting, in ms. Defaults to 2000. */
  retryMs?: number;
};

export type Connection = { close: () => void };

export function connect(path: string, handlers: Handlers, options: Options = {}): Connection {
  const retryMs = options.retryMs ?? 2000;
  let socket: WebSocket | null = null;
  let closedByUs = false;
  let heartbeat: ReturnType<typeof setInterval> | undefined;
  let retryTimer: ReturnType<typeof setTimeout> | undefined;

  const scheduleReconnect = () => {
    clearInterval(heartbeat);
    if (closedByUs) return;
    retryTimer = setTimeout(open, retryMs);
  };

  function open() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${location.host}${path}`);

    socket.onopen = () => {
      // Heartbeat only: the server doesn't parse this payload, it just
      // keeps the connection alive through idle-timing proxies (see
      // ws_routes.py — `receive_text()` in a loop, discarded).
      heartbeat = setInterval(() => socket?.send("ping"), 25_000);
    };

    socket.onmessage = (event: MessageEvent<string>) => {
      let message: ServerMessage;
      try {
        message = JSON.parse(event.data) as ServerMessage;
      } catch {
        return; // malformed frame — ignore rather than throw
      }
      const handler = handlers[message.type] as ((m: ServerMessage) => void) | undefined;
      handler?.(message); // unknown/unhandled types are silently ignored
    };

    // A failed handshake surfaces here as `error` immediately followed by
    // `close` — there is no separate recovery to do on `error` beyond not
    // letting it throw, so this handler exists only to swallow it quietly.
    socket.onerror = () => {};

    socket.onclose = scheduleReconnect;
  }

  open();

  return {
    close() {
      closedByUs = true;
      clearInterval(heartbeat);
      clearTimeout(retryTimer);
      socket?.close();
    },
  };
}

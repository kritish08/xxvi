// Shared, content-free fetch plumbing. Both lib/client.ts (pre-gate: the
// main chunk) and lib/run-client.ts (run-phase: only reachable from behind
// the gate, see that file's header) build their route wrappers on top of
// this. Nothing in here names a single route, a screen, or a game -- it is
// pure transport, so it is safe for both chunks to depend on without either
// one dragging the other's strings along with it (Vite/Rollup bundles a
// module into every chunk that imports it, and a generic `call`/`post` pair
// has nothing in it worth hiding).

/** Thrown by every `call`/`post` on a non-2xx response. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, path: string) {
    super(`${status} ${path}`);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new ApiError(response.status, path);
  }
  return (await response.json()) as T;
}

export const post = <T,>(path: string, body?: unknown): Promise<T> =>
  call<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });

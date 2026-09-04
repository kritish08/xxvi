// The front door. Rate-limited server-side (xxvi/gates/service.py) but
// never hard-locks, so a rejection must always leave him able to retry —
// the submit button is disabled only by input validity/in-flight state,
// never by a prior failure.

import { useEffect, useRef, useState } from "react";
import { ApiError, runApi } from "../lib/run-client";

// Length is deliberately a RANGE, not a fixed 12. An earlier version required
// exactly twelve characters, which would have made the real activation code
// physically untypeable — the submit button never enabling, with no operator
// bypass, at midnight. The code is derived from a riddle answered by email, so
// its length is whatever that answer is; the UI must not dictate it.
const MIN_KEY_CHARS = 6;
const MAX_KEY_CHARS = 24;

/** Everything that is not a letter or digit is decoration. He may be sent a
 *  code wrapped in punctuation and will type it verbatim, so `##ABC123##`,
 *  `abc-123` and `ABC123` must all reduce to the same value. This is the
 *  canonical form and it is exactly what gets sent and hashed — no dashes,
 *  no separators, so there is no format to get wrong on either side. */
export function canonicalKey(raw: string): string {
  return raw.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, MAX_KEY_CHARS);
}

/** Cosmetic only: groups the canonical form into fours so it reads like a
 *  product key on screen. Never sent anywhere. */
function displayKey(canonical: string): string {
  return canonical.match(/.{1,4}/g)?.join("-") ?? canonical;
}

export function Activation({ onDone }: { onDone: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (error) inputRef.current?.focus();
  }, [error]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // Send the canonical form, never the dashed display form — the server
      // compares against a hash of exactly this string.
      await runApi.activate(canonicalKey(value));
      onDone();
    } catch (err) {
      // run-client.ts's own guidance: a 409 here means "already activated" —
      // someone (or a retried request) beat this one to it. The right
      // response is to resync, not to report a failure that didn't happen.
      if (err instanceof ApiError && err.status === 409) {
        onDone();
        return;
      }
      // Server-side lockout is a timed cooldown, not permanent (see
      // GateOutcome.LOCKED) — the client can't distinguish "wrong" from
      // "locked" from the status code alone, and shouldn't claim to.
      setError("that key isn't valid — check it and try again");
    } finally {
      setBusy(false);
    }
  };

  const canonical = canonicalKey(value);
  const valid =
    canonical.length >= MIN_KEY_CHARS && canonical.length <= MAX_KEY_CHARS;

  return (
    <form className="activation" onSubmit={submit}>
      <div className="label activation__label">product activation</div>
      <h1>enter product key</h1>
      <input
        ref={inputRef}
        className="activation__input"
        value={value}
        onChange={(e) => setValue(displayKey(canonicalKey(e.target.value)))}
        placeholder="XXXX-XXXX-XXXX"
        aria-label="product key"
        aria-invalid={error ? true : undefined}
        inputMode="text"
        autoComplete="off"
        spellCheck={false}
        autoFocus
      />
      <button type="submit" disabled={busy || !valid}>
        {busy ? "activating…" : "activate"}
      </button>
      {/* Always mounted, never conditionally rendered (design-system.md §6,
          "no layout shift, ever" — and an aria-live region announces
          reliably only if it existed before its content changed). The
          non-breaking space reserves the line's height while empty. */}
      <p className="activation__error" role="alert">
        {error ?? " "}
      </p>
    </form>
  );
}

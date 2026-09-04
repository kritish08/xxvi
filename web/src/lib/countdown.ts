// Formats a server-supplied remaining-seconds value for display.
//
// The gate's open/closed state is a server decision (`SessionInfo.live`),
// never a client one. This module has no knowledge of that boolean at all
// -- it only turns a number of seconds into a string. The caller (App.tsx /
// ComingSoon.tsx) ticks that number down locally between polls purely for a
// smooth-looking display and re-syncs it to the server's value on every
// poll, so local clock drift can never cause the countdown to reach zero
// before the server actually opens the gate.

const pad = (value: number) => String(value).padStart(2, "0");

/** Formats a server-supplied remaining-seconds value as DD:HH:MM:SS. */
export function formatCountdown(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return [days, hours, minutes, seconds % 60].map(pad).join(":");
}

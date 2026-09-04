// ws-messages.ts is a hand-written mirror of server/xxvi/realtime/messages.py
// (see the header comment on both files) and, as of this task, had no
// automated guard against the two drifting apart — noted by the task-14
// scaffold's own report as a gap. This is that guard.
//
// It does not need to be elegant. It needs to fail loudly the moment
// someone edits a message's discriminator, adds/removes a message type, or
// changes which types are in the `ServerMessage` union on one side and not
// the other. So: a small, deliberately literal regex parse of both files —
// not a real Python or TypeScript parser — comparing:
//
//   1. the set of message class/type names on each side,
//   2. each one's `type` discriminator literal,
//   3. the set of names folded into the `ServerMessage` union on each side,
//   4. that nothing is defined but left out of its own side's union.
//
// A change that only touches one file (rename a discriminator, add a new
// message class, drop one from the union) breaks one of these assertions
// with a message naming exactly what's missing/extra/mismatched.

/// <reference types="node" />
// tsconfig.test.json's `types` array doesn't include "node" (no other test
// in this project touches the filesystem), so this file pulls in just
// enough of @types/node — already a devDependency — for itself via a
// triple-slash reference rather than widening the shared tsconfig for
// every test file.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { describe, expect, it } from "vitest";

const here = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(here, "..", "..");
const PY_PATH = path.join(REPO_ROOT, "server", "xxvi", "realtime", "messages.py");
const TS_PATH = path.join(REPO_ROOT, "web", "src", "ws-messages.ts");

type Discriminator = { name: string; literal: string };

/** `class FooMsg(BaseModel):` ... `type: Literal["foo"] = "foo"` blocks. */
function parsePython(source: string): { classes: Discriminator[]; union: string[] } {
  const classes: Discriminator[] = [];
  // Split on class boundaries so each block only sees its own body.
  const blocks = source.split(/\nclass /).slice(1);
  for (const block of blocks) {
    const nameMatch = /^(\w+)\(BaseModel\):/.exec(block);
    const literalMatch = /type:\s*Literal\["([^"]+)"\]/.exec(block);
    if (nameMatch && literalMatch) {
      classes.push({ name: nameMatch[1], literal: literalMatch[1] });
    }
  }

  const unionMatch = /ServerMessage\s*=\s*Annotated\[([\s\S]*?),\s*Field\(discriminator="type"\)/.exec(source);
  if (!unionMatch) {
    throw new Error("messages.py: could not find the `ServerMessage = Annotated[...]` union");
  }
  const union = unionMatch[1]
    .split("|")
    .map((s) => s.trim())
    .filter(Boolean);

  return { classes, union };
}

/** `export type FooMsg = { type: "foo"; ... };` blocks, plus the
 *  `export type ServerMessage = | Foo | Bar | ...;` union. */
function parseTypeScript(source: string): { classes: Discriminator[]; union: string[] } {
  const classes: Discriminator[] = [];
  // \s* (not \s*\n\s*) so this matches both the multi-line message types
  // and the couple written on one line (e.g. `ToastMsg`, `OperatorPresenceMsg`).
  const typeRe = /export type (\w+) = \{\s*type:\s*"([^"]+)"/g;
  for (const match of source.matchAll(typeRe)) {
    classes.push({ name: match[1], literal: match[2] });
  }

  const unionMatch = /export type ServerMessage =([\s\S]*?);/.exec(source);
  if (!unionMatch) {
    throw new Error("ws-messages.ts: could not find `export type ServerMessage = ...;`");
  }
  const union = unionMatch[1]
    .split("|")
    .map((s) => s.trim())
    .filter(Boolean);

  return { classes, union };
}

describe("ws-messages.ts mirrors server/xxvi/realtime/messages.py", () => {
  const py = parsePython(readFileSync(PY_PATH, "utf8"));
  const ts = parseTypeScript(readFileSync(TS_PATH, "utf8"));

  it("parsed at least one message type from each file (parser sanity check)", () => {
    // If this fails, the regexes above have stopped matching the real file
    // shape (e.g. someone reformatted messages.py) and the rest of this
    // suite is vacuously passing — treat that as a failure too.
    expect(py.classes.length).toBeGreaterThan(0);
    expect(ts.classes.length).toBeGreaterThan(0);
  });

  it("declares the same set of message types on both sides", () => {
    const pyNames = py.classes.map((c) => c.name).sort();
    const tsNames = ts.classes.map((c) => c.name).sort();
    expect(tsNames).toEqual(pyNames);
  });

  it("agrees on every message's `type` discriminator literal", () => {
    const tsByName = new Map(ts.classes.map((c) => [c.name, c.literal]));
    for (const { name, literal } of py.classes) {
      expect(tsByName.get(name), `ws-messages.ts is missing ${name}`).toBe(literal);
    }
  });

  it("includes the same message types in the ServerMessage union on both sides", () => {
    expect(ts.union.sort()).toEqual(py.union.sort());
  });

  it("py: every declared message class is in ServerMessage (nothing orphaned)", () => {
    expect(py.union.sort()).toEqual(py.classes.map((c) => c.name).sort());
  });

  it("ts: every declared message type is in ServerMessage (nothing orphaned)", () => {
    expect(ts.union.sort()).toEqual(ts.classes.map((c) => c.name).sort());
  });
});

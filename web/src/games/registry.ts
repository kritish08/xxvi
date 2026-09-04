// All four mechanics registered up front, per the content schema
// (server/xxvi/content/schema.py::GameSlot.mechanic). "update" and "drift"
// are Task 19's, "trophy_run" is Task 20's — each lands as a wholesale
// replacement of its placeholder file (SystemUpdate.tsx, StickDrift.tsx,
// TrophyRun.tsx), not a merge into this file, so this map's shape doesn't
// change at that point, only the imports' targets do.

import type { ComponentType } from "react";
import { SimonSays } from "./SimonSays";
import { SystemUpdate } from "./SystemUpdate";
import { StackTower } from "./StackTower";
import { StickDrift } from "./StickDrift";
import { TrophyRun } from "./TrophyRun";
import type { GameProps } from "./types";

export const GAMES: Record<string, ComponentType<GameProps>> = {
  simon: SimonSays,
  update: SystemUpdate,
  drift: StickDrift,
  trophy_run: TrophyRun,
  // Ported from the Kyrex coming-soon page — see StackTower.tsx's header
  // for what changed in the port and why.
  stack: StackTower,
};

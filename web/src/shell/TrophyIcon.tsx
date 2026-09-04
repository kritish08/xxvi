// Four chalice forms, one per grade, all `currentColor`-driven so the
// KIDDIE/DEVIL palette swap and the fixed grade colours (docs/design-system.md
// §4) are free — the colour is set by the caller via CSS `color`, never
// baked into the markup. Flat, thick strokes, no gradients, no fills that
// would read as a soft shadow (§1, §8 ban list).
//
// Escalation reads in the *shape*, not just the colour, per §9 ("every
// state that uses colour also uses shape, text, or position"):
//   bronze   — plain bowl, stem, base
//   silver   — + handles, + a stem band
//   gold     — + a flared rim
//   platinum — + a crest above the rim, wider bowl. The highest-luminance
//              value in the system also gets the most elaborate form.
//
// Shared viewBox across all four so they drop into the same container at
// the same scale without per-grade layout math. The extra headroom
// (`-10 48 66` rather than `0 48 56`) exists for platinum's crest; the
// other three simply don't use it.

import type { ReactNode } from "react";

export type Grade = "bronze" | "silver" | "gold" | "platinum";

const KNOWN_GRADES: readonly Grade[] = ["bronze", "silver", "gold", "platinum"];

export function isKnownGrade(value: string): value is Grade {
  return (KNOWN_GRADES as readonly string[]).includes(value);
}

const VIEW_BOX = "0 -10 48 66";
const STROKE = 4;

type IconProps = { className?: string };

function Bowl() {
  return <path d="M10 6 L10 22 C10 30 16 34 24 34 C32 34 38 30 38 22 L38 6" />;
}

function Rim() {
  return <path d="M8 6 L40 6" />;
}

function Stem() {
  return <path d="M24 34 L24 46" />;
}

function Base() {
  return <path d="M13 46 L35 46" />;
}

function Handles() {
  return (
    <>
      <path d="M10 10 C2 10 2 22 10 22" />
      <path d="M38 10 C46 10 46 22 38 22" />
    </>
  );
}

function StemBand() {
  return <path d="M19 39 L29 39" />;
}

function FlaredRim() {
  return (
    <>
      <path d="M8 6 L3 1" />
      <path d="M40 6 L45 1" />
    </>
  );
}

function shell(children: ReactNode, className?: string) {
  return (
    <svg
      className={className}
      viewBox={VIEW_BOX}
      fill="none"
      stroke="currentColor"
      strokeWidth={STROKE}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

function BronzeIcon({ className }: IconProps) {
  return shell(
    <>
      <Rim />
      <Bowl />
      <Stem />
      <Base />
    </>,
    className,
  );
}

function SilverIcon({ className }: IconProps) {
  return shell(
    <>
      <Rim />
      <Bowl />
      <Handles />
      <Stem />
      <StemBand />
      <Base />
    </>,
    className,
  );
}

function GoldIcon({ className }: IconProps) {
  return shell(
    <>
      <FlaredRim />
      <Rim />
      <Bowl />
      <Handles />
      <Stem />
      <StemBand />
      <Base />
    </>,
    className,
  );
}

function PlatinumIcon({ className }: IconProps) {
  return shell(
    <>
      {/* the crest — nothing else in the set carries one */}
      <path d="M24 -8 L28 -2 L24 4 L20 -2 Z" />
      <FlaredRim />
      <path d="M6 6 L6 22 C6 32 14 38 24 38 C34 38 42 32 42 22 L42 6" />
      <path d="M6 10 C-3 10 -3 24 6 24" />
      <path d="M42 10 C51 10 51 24 42 24" />
      <path d="M24 38 L24 46" />
      <StemBand />
      <Base />
    </>,
    className,
  );
}

const ICONS: Record<Grade, (props: IconProps) => ReactNode> = {
  bronze: BronzeIcon,
  silver: SilverIcon,
  gold: GoldIcon,
  platinum: PlatinumIcon,
};

/** Falls back to the bronze form for a grade the client doesn't recognise
 *  (the wire type is `string`, not a literal union — see ws-messages.ts's
 *  comment on why the *client's* TrophyPopMsg union is stricter than the
 *  server's `grade: str`). Never throws, never renders nothing. */
export function TrophyIcon({ grade, className }: { grade: string; className?: string }) {
  const Icon = ICONS[isKnownGrade(grade) ? grade : "bronze"];
  return <Icon className={className} />;
}

// The run so far: who it is for, how far in, what he has answered, what he
// has won. Reachable at any time from the chrome, as an overlay — it is a
// thing you glance at mid-run, not a screen the run routes you to.
//
// Everything here comes from GET /api/run/profile, which only ever
// describes CLEARED segments. That boundary lives on the server on purpose
// (run_routes.py::profile): this component could not leak an unanswered
// question even if it tried, because the data never arrives.

import { useEffect, useState } from "react";
import { runApi, type ProfileView } from "../lib/run-client";
import type { TrophyView } from "../lib/client";
// `dossier`, not `profile`: shell/ProfileSelect.tsx has used `.profile`
// for its avatar tiles since the beginning, and naming this overlay the
// same thing applied `position: fixed; inset: 0` to both of them — the two
// tiles stacked on top of each other and the names rendered at overlay
// size. Same word, two different screens; the CSS namespace is the one
// place that had to pick.
import "./dossier.css";

type Props = {
  /** Names and grades for the ids the profile returns. Already masked
   *  server-side for hidden trophies he has not earned. */
  trophies: TrophyView[];
  onClose: () => void;
};

export function Profile({ trophies, onClose }: Props) {
  const [data, setData] = useState<ProfileView | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void runApi
      .getProfile()
      .then((p) => !cancelled && setData(p))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const earned = data ? new Set(data.trophies) : new Set<string>();
  const won = trophies.filter((t) => earned.has(t.id));

  return (
    <section className="dossier" role="dialog" aria-modal="true" aria-label="profile">
      <div className="dossier__inner">
        <p className="label dossier__eyebrow">profile</p>
        <h2 className="dossier__name">{data ? data.recipient : " "}</h2>

        {failed && <p role="alert">could not load the profile. try again.</p>}

        {data && (
          <>
            <dl className="dossier__stats">
              <div>
                <dt className="label">progress</dt>
                <dd>
                  {data.cleared}
                  <span className="dossier__of"> / {data.total_segments}</span>
                </dd>
              </div>
              <div>
                <dt className="label">mode</dt>
                <dd>{data.difficulty ?? "—"}</dd>
              </div>
              {data.lives !== null && (
                <div>
                  <dt className="label">lives</dt>
                  <dd>{data.lives}</dd>
                </div>
              )}
              <div>
                <dt className="label">trophies</dt>
                <dd>{data.trophies.length}</dd>
              </div>
            </dl>

            <h3 className="label dossier__section">answered</h3>
            {data.answered.length === 0 ? (
              <p className="dossier__empty">nothing yet.</p>
            ) : (
              <ol className="dossier__answers">
                {data.answered.map((a) => (
                  <li key={a.segment}>
                    <p className="dossier__q">{a.prompt}</p>
                    <p className="dossier__a">{a.answer}</p>
                  </li>
                ))}
              </ol>
            )}

            <h3 className="label dossier__section">trophies</h3>
            {won.length === 0 ? (
              <p className="dossier__empty">none yet.</p>
            ) : (
              <ul className="dossier__trophies">
                {won.map((t) => (
                  <li key={t.id} className={`dossier__trophy dossier__trophy--${t.grade}`}>
                    <span className="dossier__trophy-name">{t.name}</span>
                    <span className="label dossier__trophy-grade">{t.grade}</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}

        <button className="dossier__close" onClick={onClose} autoFocus>
          close
        </button>
      </div>
    </section>
  );
}

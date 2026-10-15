import { useMemo } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Matrix } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { DESK, SEATS, TONE_WORDS, deskAt, desks as deskList, everyone, over, seatAt, tallyWords, unseated } from "../lib/classroom";
import type { Tone } from "../lib/status";
import { useLoad } from "../lib/useLoad";
import { ClassroomPicture } from "../ui/ClassroomArt";
import { Problem } from "../ui/Drawer";

const KEY: Tone[] = ["green", "amber", "red", "grey"];

const people = (n: number) => `${n} ${n === 1 ? "person" : "people"}`;

/** Game Mode's home: a classroom in Simple WMS's isometric view, a desk for
 * each role with its people sitting at it, coloured by how current they
 * are. Drawn from the matrix, so it says what the matrix says. Each desk's
 * name opens the matrix at that role; each person opens their page. */
export function Classroom() {
  const { me, can } = useAuth();
  const matrix = useLoad(() => api.get<Matrix>("/v1/matrix"), []);
  const desks = useMemo(() => (matrix.data ? deskList(matrix.data) : null), [matrix.data]);
  const standing = matrix.data ? unseated(matrix.data) : [];
  const all = matrix.data ? everyone(matrix.data) : null;
  const headcount = matrix.data?.people.length ?? 0;
  const seesPeople = can("people:read");

  return (
    <main className="classroom">
      <div className="flex flex-wrap items-end gap-3">
        <div className="mr-auto flex flex-col gap-1">
          <h1>Classroom</h1>
          {all && headcount > 0 && <div className="small">{people(headcount)}: {tallyWords(all)}</div>}
          {standing.length > 0 && (
            <div className="small">
              {standing.length === 1 ? "1 person has" : `${standing.length} people have`} no role yet, so no desk.
              {seesPeople && <> <Link to="/people">Give them one under People</Link>.</>}
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-2" aria-label="Key">
          {KEY.map((t) => <span key={t} className={`pill t-${t}`}><span className={`dot ${t}`} aria-hidden="true" />{TONE_WORDS[t]}</span>)}
        </div>
      </div>
      <Problem error={matrix.error} />
      {!desks && !matrix.error && <div className="small" aria-live="polite">Loading…</div>}
      {desks && desks.length === 0 && (
        <div className="card small">
          {me?.permission === "supervisor"
            ? "Nobody in your team has a role yet, so no desks."
            : "No desks yet. Add roles, then give people roles under People: each role gets a desk."}
        </div>
      )}
      {desks && desks.length > 0 && (
        <div className="room">
          <ClassroomPicture desks={desks} />
          <ul className="desks" aria-label="Desks">
            {desks.map((d, i) => {
              const spot = deskAt(i);
              const words = tallyWords(d.tally);
              const more = d.people.length - SEATS;
              return (
                <li key={d.key}>
                  <Link to={`/matrix?role=${encodeURIComponent(d.key)}`} className="desktag"
                        style={over(desks.length, spot.x + DESK.w / 2, spot.y, 70)}
                        aria-label={`${d.name}: ${people(d.people.length)}, ${words}. Open in the matrix`}>
                    {d.name}{more > 0 && <span className="more">+{more}</span>}
                  </Link>
                  {seesPeople && (
                    <ul aria-label={`At the ${d.name} desk`}>
                      {d.people.slice(0, SEATS).map((p, k) => {
                        const seat = seatAt(spot, k);
                        return (
                          <li key={p.code}>
                            <Link to={`/people?person=${encodeURIComponent(p.code)}`} className="seat"
                                  style={over(desks.length, seat.x, seat.y, 18)}
                                  aria-label={`${p.name}: ${TONE_WORDS[p.tone]}`} title={`${p.name}: ${TONE_WORDS[p.tone]}`} />
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </main>
  );
}

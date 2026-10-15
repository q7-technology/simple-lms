/** The classroom, drawn in Simple WMS's isometric view: inline SVG, no
 * image files, no game engine. It says nothing the links laid over it
 * don't, so screen readers skip it (aria-hidden) and read those. */
import type { ReactNode } from "react";
import { DESK, SEATS, WALL, deskAt, roomSize, seatAt, viewBox, type Desk } from "../lib/classroom";
import { LEFT, RIGHT, TOP, scr } from "../lib/iso";
import type { Tone } from "../lib/status";

type Faces = [top: string, left: string, right: string];

const WOOD: Faces = ["#ECC994", "#D7A96B", "#BC8D52"];
const BLUE: Faces = ["#5B93D6", "#2F6FB8", "#23558E"];
const FILL: Record<Tone, string> = { green: "#1F8A5B", amber: "#E8A317", red: "#C9343D", grey: "#8A95A5" };

/** A box standing on the floor (or at height z), as Simple WMS draws one. */
function Box({ x, y, w, d, h, z = 0, faces }: { x: number; y: number; w: number; d: number; h: number; z?: number; faces: Faces }) {
  const [top, left, right] = faces;
  return (
    <g>
      <rect x={x} y={-(z + h)} width={w} height={h} fill={left} transform={LEFT(y + d)} />
      <rect x={y} y={-(z + h)} width={d} height={h} fill={right} transform={RIGHT(x + w)} />
      <rect x={x} y={y} width={w} height={d} fill={top} transform={TOP(z + h)} />
    </g>
  );
}

/** The floor, the two back walls, the board and the teacher's desk. */
function Room({ count }: { count: number }) {
  const { w, d } = roomSize(count);
  return (
    <g>
      <rect x={0} y={0} width={w} height={d} rx={12} fill="#EEF2F7" transform={TOP(0)} />
      <rect x={0} y={-WALL} width={w} height={WALL} fill="#DCE5F1" transform={LEFT(0)} />
      <rect x={0} y={-WALL} width={d} height={WALL} fill="#C9D6E8" transform={RIGHT(0)} />
      {/* the board, on the front wall, and its chalk */}
      <rect x={170} y={-100} width={310} height={66} rx={4} fill="#C8A36A" transform={LEFT(0)} />
      <rect x={176} y={-95} width={298} height={56} rx={2} fill="#2E5E4E" transform={LEFT(0)} />
      <rect x={196} y={-80} width={120} height={3} rx={1.5} fill="#E8F0FA" opacity={0.7} transform={LEFT(0)} />
      <rect x={196} y={-68} width={180} height={3} rx={1.5} fill="#E8F0FA" opacity={0.5} transform={LEFT(0)} />
      <Box x={250} y={70} w={150} h={36} d={56} faces={BLUE} />
    </g>
  );
}

/** One person at their desk, seen from behind, facing the board. Someone
 * who needs training has a "!" over their head, so it isn't colour alone. */
function Pupil({ tone, at }: { tone: Tone; at: [number, number] }) {
  const [x, y] = at;
  return (
    <g transform={`translate(${x} ${y})`} data-tone={tone}>
      {/* the hop moves this inner group, so it never undoes the place above */}
      <g className={tone === "red" ? "hop" : undefined}>
        <path d="M-9 0V-14a9 9 0 0 1 18 0V0Z" fill={FILL[tone]} />
        <circle cx="0" cy="-29" r="7" fill={FILL[tone]} />
        {tone === "red" && <text x="0" y="-40" textAnchor="middle" fontSize="13" fontWeight="800" fill="#A3242C">!</text>}
      </g>
    </g>
  );
}

/** The room with a desk for each role and up to six people at each, those
 * who need a look first; drawn back to front, so nearer things cover
 * farther ones. With no desks given it is the empty room. */
export function ClassroomPicture({ desks }: { desks: Desk[] }) {
  const box = viewBox(desks.length);
  const items: [depth: number, node: ReactNode][] = [];
  desks.forEach((desk, i) => {
    const spot = deskAt(i);
    items.push([spot.x + spot.y, <Box key={`desk-${desk.key}`} x={spot.x} y={spot.y} w={DESK.w} d={DESK.d} h={DESK.h} faces={WOOD} />]);
    desk.people.slice(0, SEATS).forEach((p, k) => {
      const seat = seatAt(spot, k);
      items.push([seat.x + seat.y, <Pupil key={`${desk.key}-${p.code}`} tone={p.tone} at={scr(seat.x, seat.y)} />]);
    });
  });
  items.sort((a, b) => a[0] - b[0]);
  return (
    <svg viewBox={`${box.x} ${box.y} ${box.w} ${box.h}`} aria-hidden="true" focusable="false" className="roompic">
      <Room count={desks.length} />
      {items.map(([, node]) => node)}
    </svg>
  );
}

const EMPTY: Desk[] = ["a", "b", "c", "d", "e", "f"].map((key) => ({
  key, name: "", people: [], tally: { red: 0, amber: 0, green: 0, grey: 0 },
}));

/** Behind a screen's drawer: the classroom with its desks and nobody at
 * them, so nothing of anyone's shows through. */
export function ClassroomBackdrop() {
  return <div className="backdrop" aria-hidden="true"><ClassroomPicture desks={EMPTY} /></div>;
}

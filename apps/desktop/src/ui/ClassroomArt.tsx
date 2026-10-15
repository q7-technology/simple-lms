/** The classroom, drawn in Simple WMS's isometric view: inline SVG, no
 * image files, no game engine. It says nothing the links laid over it
 * don't, so screen readers skip it (aria-hidden) and read those. Boxes are
 * drawn as Simple WMS draws its pallets: three rects under the TOP, LEFT
 * and RIGHT face transforms, back to front. */
import { memo, type ReactNode } from "react";
import {
  DESK, SEATS, SIGN, WALL, WALL_T, deskAt, roomSize, seatAt, signAt, teacherDesk, viewBox, type Desk,
} from "../lib/classroom";
import { LEFT, RIGHT, TOP, scr } from "../lib/iso";
import type { Tone } from "../lib/status";

type Faces = [top: string, left: string, right: string];

// Simple WMS's pallet wood, its darker base for the teacher's desk, and its forklift mast for metal
const WOOD: Faces = ["#ECC994", "#D7A96B", "#BC8D52"];
const DARK_WOOD: Faces = ["#C99A5E", "#B4844A", "#9A6E3A"];
const METAL: Faces = ["#56607A", "#3A4256", "#2A3142"];
const SEAT: Faces = ["#9AA6BD", "#7C89A3", "#68748D"];
const WHITE: Faces = ["#FFFFFF", "#EEF2FA", "#D3DCEC"];

/** A person's colour: dark enough to stand out 3:1 against the floor. */
export const FILL: Record<Tone, string> = { green: "#1F8A5B", amber: "#B06A06", red: "#C9343D", grey: "#6B7787" };
const SKIN = "#F2CFAE";
const HAIR = ["#3B2A20", "#6B4A2F", "#1F1B18", "#A7743A", "#5A3A28", "#2E2A33"];

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

/** A table: four legs and a top. */
function Table({ x, y, w, d, h, faces, panel }: { x: number; y: number; w: number; d: number; h: number; faces: Faces; panel?: Faces }) {
  const leg = (lx: number, ly: number) => <Box x={lx} y={ly} w={4} d={4} h={h - 4} faces={METAL} />;
  return (
    <g>
      {leg(x + 3, y + 3)}{leg(x + w - 7, y + 3)}
      {/* a modesty panel along the side toward the board */}
      {panel && <Box x={x + 6} y={y + 2} w={w - 12} d={3} h={h - 16} z={12} faces={panel} />}
      {leg(x + 3, y + d - 7)}{leg(x + w - 7, y + d - 7)}
      <Box x={x} y={y} w={w} d={d} h={4} z={h - 4} faces={faces} />
    </g>
  );
}

/** A stool: four legs and a seat. */
function Stool({ x, y }: { x: number; y: number }) {
  return (
    <g>
      <Box x={x - 7} y={y - 6} w={2.5} d={2.5} h={18} faces={METAL} />
      <Box x={x + 4.5} y={y - 6} w={2.5} d={2.5} h={18} faces={METAL} />
      <Box x={x - 7} y={y + 3.5} w={2.5} d={2.5} h={18} faces={METAL} />
      <Box x={x + 4.5} y={y + 3.5} w={2.5} d={2.5} h={18} faces={METAL} />
      <Box x={x - 9} y={y - 8} w={18} d={16} h={3} z={18} faces={SEAT} />
    </g>
  );
}

/** What each colour means as a shape, so it is never colour alone: "!"
 * needs training, a clock runs out soon, a tick is current, a dash has
 * nothing due. Drawn about (0, 0), 16 across. */
export function StatusMark({ tone }: { tone: Tone }) {
  const ink = { fill: "none", stroke: "#fff", strokeWidth: 1.9, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return (
    <g>
      <circle r="7.5" fill={FILL[tone]} stroke="#fff" strokeWidth="1.5" />
      {tone === "red" && <><path d="M0 -4V0.6" {...ink} strokeWidth={2.2} /><circle cy="3.6" r="1.2" fill="#fff" /></>}
      {tone === "amber" && <><circle r="4.3" {...ink} strokeWidth={1.4} /><path d="M0 -2.6V0L1.9 1.3" {...ink} strokeWidth={1.4} /></>}
      {tone === "green" && <path d="M-3.4 0.2L-1 2.6L3.5 -2.4" {...ink} />}
      {tone === "grey" && <path d="M-3 0H3" {...ink} />}
    </g>
  );
}

/** The key's version of a mark, for beside its words. */
export function MarkIcon({ tone }: { tone: Tone }) {
  return (
    <svg width="16" height="16" viewBox="-8.5 -8.5 17 17" aria-hidden="true" focusable="false" className="mark">
      <StatusMark tone={tone} />
    </svg>
  );
}

/** One person on their chair at their desk, seen from behind as they face
 * the board: shoulders and head above the desk, in their colour, with
 * their mark over their head. */
function Pupil({ tone, hair, at }: { tone: Tone; hair: string; at: [number, number] }) {
  const [x, y] = at;
  return (
    <g transform={`translate(${x} ${y})`} data-tone={tone}>
      {/* the hop moves this inner group, so it never undoes the place above */}
      <g className={tone === "red" ? "hop" : undefined}>
        <path d="M-10.5 -20V-40C-10.5 -46 -6 -49 0 -49C6 -49 10.5 -46 10.5 -40V-20Z" fill={FILL[tone]} />
        <path d="M-10.5 -40C-10.5 -46 -6 -49 0 -49C6 -49 10.5 -46 10.5 -40" fill="none" stroke="#000" strokeOpacity="0.12" strokeWidth="1.2" />
        <rect x="-3" y="-53" width="6" height="6" rx="2" fill={SKIN} />
        <circle cy="-58" r="7.5" fill={SKIN} />
        <path d="M-7.7 -57.2A7.7 7.9 0 1 1 7.7 -57.2C6 -54.6 -6 -54.6 -7.7 -57.2Z" fill={hair} />
        <g transform="translate(0 -76)"><StatusMark tone={tone} /></g>
      </g>
    </g>
  );
}

/** The floor, the walls with their windows, door, board and clock, the
 * shelf and the plant, and the teacher's desk. Nothing in it is data. */
function Room({ count }: { count: number }) {
  const { w, d } = roomSize(count);
  const board = { x: w / 2 - 180, w: 360 };
  const teacher = teacherDesk(count);
  const windows: number[] = [];
  for (let at = 70; at + 96 < d - 170; at += 210) windows.push(at);
  const door = d - 130;
  const chalk = { stroke: "#E8F0FA", strokeWidth: 2.2, fill: "none", strokeLinecap: "round" as const, opacity: 0.75 };
  return (
    <g>
      <defs>
        {/* a calm tiled floor, its tiles drawn flat and laid down with the floor */}
        <pattern id="lms-floor" width="60" height="60" patternUnits="userSpaceOnUse">
          <rect width="60" height="60" fill="#EEF2F7" />
          <rect width="30" height="30" fill="#E9EEF5" />
          <rect x="30" y="30" width="30" height="30" fill="#E9EEF5" />
          <path d="M0 0.5H60M0.5 0V60" stroke="#DCE4EE" strokeWidth="1" />
        </pattern>
      </defs>
      {/* the floor */}
      <rect x={0} y={0} width={w} height={d} fill="url(#lms-floor)" transform={TOP(0)} />
      {/* the side wall, in shade, with its windows and the door */}
      <rect x={0} y={-WALL} width={d} height={WALL} fill="#D3DEEC" transform={RIGHT(0)} />
      <rect x={0} y={-10} width={d} height={10} fill="#B9C6D8" transform={RIGHT(0)} />
      {windows.map((at) => (
        <g key={at} transform={RIGHT(0)}>
          <rect x={at} y={-114} width={96} height={68} rx={2} fill="#F7F9FC" />
          <rect x={at + 5} y={-109} width={86} height={58} fill="#BCD6F1" />
          <path d={`M${at + 14} -60L${at + 40} -104M${at + 30} -56L${at + 52} -94`} stroke="#E4F0FB" strokeWidth="5" strokeLinecap="round" />
          <rect x={at + 46} y={-109} width={4} height={58} fill="#F7F9FC" />
          <rect x={at + 5} y={-82} width={86} height={4} fill="#F7F9FC" />
          <rect x={at - 3} y={-48} width={102} height={4} fill="#E3E9F2" />
        </g>
      ))}
      <g transform={RIGHT(0)}>
        <rect x={door - 4} y={-108} width={72} height={108} fill="#B4844A" />
        <rect x={door} y={-104} width={64} height={104} fill="#D7A96B" />
        <rect x={door + 8} y={-96} width={48} height={36} rx={2} fill="#C99A5E" />
        <rect x={door + 8} y={-52} width={48} height={40} rx={2} fill="#C99A5E" />
        <rect x={door + 52} y={-58} width={8} height={4} rx={2} fill="#56607A" />
      </g>
      {/* the front wall, in the light, with the board, the clock and the skirting */}
      <rect x={0} y={-WALL} width={w} height={WALL} fill="#E3EAF4" transform={LEFT(0)} />
      <rect x={0} y={-10} width={w} height={10} fill="#C3CFDF" transform={LEFT(0)} />
      <g transform={LEFT(0)}>
        <rect x={board.x} y={-122} width={board.w} height={76} rx={4} fill="#B4844A" />
        <rect x={board.x + 6} y={-116} width={board.w - 12} height={64} rx={2} fill="#2E5E4E" />
        <text x={board.x + 26} y={-90} fill="#E8F0FA" opacity={0.85} fontSize="15" fontWeight="700" fontStyle="italic"
              fontFamily="Manrope, system-ui, sans-serif">Today: stay current</text>
        <path d={`M${board.x + 26} -74q12 -8 24 0t24 0t24 0M${board.x + 120} -74q10 -7 20 0t20 0`} {...chalk} />
        <path d={`M${board.x + 236} -100l30 0M${board.x + 236} -88l52 0M${board.x + 236} -76l40 0`} {...chalk} />
        <circle cx={board.x + 222} cy={-100} r={2} fill="#E8F0FA" opacity={0.75} />
        <circle cx={board.x + 222} cy={-88} r={2} fill="#E8F0FA" opacity={0.75} />
        <circle cx={board.x + 222} cy={-76} r={2} fill="#E8F0FA" opacity={0.75} />
        {/* the clock */}
        <circle cx={board.x + board.w + 50} cy={-104} r={13} fill="#FFFFFF" stroke="#56607A" strokeWidth="2.5" />
        <path d={`M${board.x + board.w + 50} -104v-8M${board.x + board.w + 50} -104h6`} stroke="#3A4256" strokeWidth="2" strokeLinecap="round" />
      </g>
      {/* the chalk ledge */}
      <Box x={board.x + 6} y={0} w={board.w - 12} d={5} h={3} z={44} faces={DARK_WOOD} />
      {/* the walls' tops and ends, so they have some thickness */}
      <rect x={-WALL_T} y={-WALL_T} width={w + WALL_T} height={WALL_T} fill="#F7F9FC" transform={TOP(WALL)} />
      <rect x={-WALL_T} y={0} width={WALL_T} height={d} fill="#F7F9FC" transform={TOP(WALL)} />
      <rect x={-WALL_T} y={-WALL} width={WALL_T} height={WALL} fill="#B9C6D8" transform={LEFT(d)} />
      <rect x={-WALL_T} y={-WALL} width={WALL_T} height={WALL} fill="#CBD6E6" transform={RIGHT(w)} />
      {/* a plant in the corner, as Simple WMS draws its trees */}
      <Box x={20} y={20} w={22} d={22} h={20} faces={["#D98B5F", "#C4744A", "#A9603A"]} />
      {(() => {
        const [px, py] = scr(31, 31, 20);
        return (
          <g>
            <rect x={px - 1.5} y={py - 12} width={3} height={12} fill="#7A6A55" />
            <circle cx={px - 9} cy={py - 18} r={10} fill="#5FB574" />
            <circle cx={px + 9} cy={py - 18} r={10} fill="#5FB574" />
            <circle cx={px} cy={py - 28} r={13} fill="#7CCB8E" />
            <circle cx={px - 5} cy={py - 33} r={6} fill="#9BDCA9" />
          </g>
        );
      })()}
      {/* a bookshelf against the front wall */}
      <Box x={w - 120} y={0} w={86} d={26} h={92} faces={DARK_WOOD} />
      <g transform={LEFT(26)}>
        {[0, 1, 2].map((shelf) => (
          <g key={shelf}>
            <rect x={w - 114} y={-86 + shelf * 28} width={74} height={22} fill="#8E6537" />
            {[0, 1, 2, 3, 4, 5, 6].map((b) => (
              <rect key={b} x={w - 112 + b * 10} y={-84 + shelf * 28 + (b % 3)} width={8} height={20 - (b % 3)}
                    fill={["#2F6FB8", "#C9343D", "#ECC994", "#1F8A5B", "#5B93D6", "#E8A317", "#F7F9FC"][(b + shelf * 2) % 7]} />
            ))}
          </g>
        ))}
      </g>
      {/* the teacher's chair, between the board and the desk, then the desk */}
      <Box x={teacher.x + 68} y={teacher.y - 40} w={24} d={4} h={24} z={20} faces={SEAT} />
      <Stool x={teacher.x + 80} y={teacher.y - 26} />
      <Table x={teacher.x} y={teacher.y} w={teacher.w} d={teacher.d} h={teacher.h} faces={DARK_WOOD} />
      <Box x={teacher.x + 18} y={teacher.y + 12} w={30} d={22} h={4} z={teacher.h} faces={["#5B93D6", "#2F6FB8", "#23558E"]} />
      <Box x={teacher.x + 20} y={teacher.y + 13} w={26} d={20} h={4} z={teacher.h + 4} faces={["#E97C83", "#C9343D", "#A3242C"]} />
      <Box x={teacher.x + 100} y={teacher.y + 14} w={26} d={18} h={1} z={teacher.h} faces={WHITE} />
      {(() => {
        const [ax, ay] = scr(teacher.x + 136, teacher.y + 22, teacher.h);
        return <g><circle cx={ax} cy={ay - 5} r={5} fill="#C9343D" /><rect x={ax - 0.8} y={ay - 13} width={1.6} height={4} fill="#7A6A55" /></g>;
      })()}
    </g>
  );
}

/** A fixed hair colour for a person, so the room doesn't change on a reload. */
function hairOf(code: string): string {
  let h = 0;
  for (const c of code) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return HAIR[h % HAIR.length];
}

/** One desk with its chairs, people and sign, drawn back to front. */
function DeskGroup({ desk, at, bare }: { desk: Desk; at: { x: number; y: number }; bare?: boolean }) {
  const seated = desk.people.slice(0, SEATS);
  const sign = signAt(at);
  return (
    <g>
      <Table x={at.x} y={at.y} w={DESK.w} d={DESK.d} h={DESK.h} faces={WOOD} panel={DARK_WOOD} />
      {/* a sheet of paper in front of each person */}
      {seated.map((p, k) => {
        const seat = seatAt(at, k);
        return <rect key={p.code} x={seat.x - 8} y={at.y + DESK.d - 20} width={16} height={12} fill="#FFFFFF" transform={TOP(DESK.h)} />;
      })}
      {!bare && Array.from({ length: SEATS }, (_, k) => {
        const seat = seatAt(at, k);
        const p = seated[k];
        return (
          <g key={k}>
            <Stool x={seat.x} y={seat.y} />
            {p && <Pupil tone={p.tone} hair={hairOf(p.code)} at={scr(seat.x, seat.y, 0)} />}
          </g>
        );
      })}
      {/* the sign's stand; its face is the desk's link, laid over the picture */}
      <Box x={sign.x + 6} y={sign.y - 6} w={3} d={4} h={SIGN.h - 2} faces={METAL} />
      <Box x={sign.x + SIGN.w - 9} y={sign.y - 6} w={3} d={4} h={SIGN.h - 2} faces={METAL} />
      <Box x={sign.x} y={sign.y - 2} w={SIGN.w} d={2} h={SIGN.h} faces={WHITE} />
    </g>
  );
}

/** The room with a desk for each role and up to six people at each, those
 * who need a look first. Desks are drawn back to front, so nearer things
 * cover farther ones. With no desks given it is the empty room. */
export function ClassroomPicture({ desks, bare }: { desks: Desk[]; bare?: boolean }) {
  const box = viewBox(desks.length);
  const items: [depth: number, node: ReactNode][] = desks.map((desk, i) => {
    const at = deskAt(i, desks.length);
    return [at.x + at.y, <DeskGroup key={desk.key} desk={desk} at={at} bare={bare} />];
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
 * them, so nothing of anyone's shows through. Placeholder desks, not the
 * real ones: the real layout needs the matrix, and loading it behind every
 * screen would be a second request for a picture that is dimmed and hidden
 * from screen readers, and would show a supervisor's team behind screens
 * that are about something else. */
export const ClassroomBackdrop = memo(function ClassroomBackdrop() {
  // bare desks, without chairs: it is faded, and it is behind every screen
  return <div className="backdrop" aria-hidden="true"><ClassroomPicture desks={EMPTY} bare /></div>;
});

/** Simple WMS's isometric view, the same angles and the same three faces
 * (apps/desktop/scripts/warehouse_layers.py there): x runs down to the
 * right, y down to the left, z straight up. A rect drawn in a face's own
 * flat coordinates and given that face's transform lands in the picture. */
const n = (v: number) => Number(v.toFixed(1));

/** The floor, or a top at height z: a rect at (x, y). */
export const TOP = (z: number) => `matrix(.866 .5 -.866 .5 0 ${n(-z)})`;
/** The face at y = y1, seen from the front left: a rect at (x, -z). */
export const LEFT = (y1: number) => `matrix(.866 .5 0 1 ${n(-0.866 * y1)} ${n(0.5 * y1)})`;
/** The face at x = x1, seen from the front right: a rect at (y, -z). */
export const RIGHT = (x1: number) => `matrix(-.866 .5 0 1 ${n(0.866 * x1)} ${n(0.5 * x1)})`;

/** Where a point of the room lands in the picture. */
export function scr(x: number, y: number, z = 0): [number, number] {
  return [n((x - y) * 0.866), n((x + y) * 0.5 - z)];
}

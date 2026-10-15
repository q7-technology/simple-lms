/** "Ding!" on a pass, made on the spot with WebAudio as Simple WMS's is: no
 * sound file to ship, cache or licence. Quiet: a cue, not an alarm. */
import { useMemo } from "react";
import { useGamePrefs } from "./game";

let ctx: AudioContext | null = null;

function audio(): AudioContext | null {
  if (ctx) return ctx;
  const w = window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext };
  const Make = w.AudioContext ?? w.webkitAudioContext;
  if (!Make) return null;
  try { ctx = new Make(); } catch { ctx = null; }
  return ctx;
}

/** A phone only plays sound a tap started: wake it on the tap that may
 * end in a ding (Hand it in, Sign), so it can sound when the answer comes. */
function wake() {
  const c = audio();
  try { if (c?.state === "suspended") void c.resume(); } catch { /* fine without */ }
}

/** A bright two-note ding. */
function ding() {
  const c = audio();
  if (!c) return;
  try {
    const now = c.currentTime;
    for (const [freq, at, length] of [[1318.5, 0, 0.5], [1760, 0.12, 0.7]]) {
      const osc = c.createOscillator();
      const gain = c.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, now + at);
      gain.gain.setValueAtTime(0.0001, now + at);
      gain.gain.exponentialRampToValueAtTime(0.15, now + at + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + at + length);
      osc.connect(gain).connect(c.destination);
      osc.start(now + at);
      osc.stop(now + at + length + 0.05);
    }
  } catch { /* a browser that won't play is fine */ }
}

/** Forget the audio context, so a test's stand-in is used (tests). */
export function forgetSound(): void {
  ctx = null;
}

/** The ding, if this device has sound on: `wake` in the tap, `ding` on the pass. */
export function useDing() {
  const [{ sound }] = useGamePrefs();
  return useMemo(() => ({
    wake: () => { if (sound) wake(); },
    ding: () => { if (sound) ding(); },
  }), [sound]);
}

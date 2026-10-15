import { useSyncExternalStore } from "react";

/** The learner app's game touches on this device, kept in this browser and
 * never sent to Simple LMS. On a shared tablet they are the tablet's: they
 * name nobody, so signing out leaves them be. */
export interface GamePrefs {
  /** "Ding!" out loud on a pass */
  sound: boolean;
}

export const GAME_PREFS_KEY = "lms.learner.game";
export const DEFAULT_PREFS: GamePrefs = { sound: true };

function read(): GamePrefs {
  try {
    const raw = window.localStorage.getItem(GAME_PREFS_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw) as Partial<GamePrefs> | null;
    return { sound: typeof parsed?.sound === "boolean" ? parsed.sound : DEFAULT_PREFS.sound };
  } catch {
    return DEFAULT_PREFS;
  }
}

let current: GamePrefs | null = null;
const listeners = new Set<() => void>();

export function getGamePrefs(): GamePrefs {
  if (!current) current = read();
  return current;
}

export function setGamePrefs(change: Partial<GamePrefs>): void {
  current = { ...getGamePrefs(), ...change };
  try { window.localStorage.setItem(GAME_PREFS_KEY, JSON.stringify(current)); } catch { /* private mode: for this visit only */ }
  for (const l of listeners) l();
}

/** Forget the copy in memory, so the next read comes from storage (tests). */
export function reloadGamePrefs(): void {
  current = null;
  for (const l of listeners) l();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => { listeners.delete(l); };
}

export function useGamePrefs(): [GamePrefs, (change: Partial<GamePrefs>) => void] {
  const prefs = useSyncExternalStore(subscribe, getGamePrefs, getGamePrefs);
  return [prefs, setGamePrefs];
}

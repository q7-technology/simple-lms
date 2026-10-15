import { useSyncExternalStore } from "react";

/** Game Mode, for whoever sits at this screen: kept in this browser, never
 * sent to Simple LMS, so one person's plain desktop is nobody else's
 * business. Off, the desktop is as it was before the classroom: the matrix
 * first, and each screen a page of its own. */
export interface GamePrefs {
  /** the classroom, with every screen opening as a drawer over it */
  classroom: boolean;
}

export const GAME_PREFS_KEY = "lms.game";
export const DEFAULT_PREFS: GamePrefs = { classroom: true };

function read(): GamePrefs {
  try {
    const raw = window.localStorage.getItem(GAME_PREFS_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw) as Partial<GamePrefs> | null;
    return { classroom: typeof parsed?.classroom === "boolean" ? parsed.classroom : DEFAULT_PREFS.classroom };
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

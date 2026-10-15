import "@testing-library/jest-dom/vitest";
import { reloadGamePrefs } from "../lib/gamePrefs";

// Game Mode is each viewer's own, kept in the browser: every test starts with the default
afterEach(() => {
  window.localStorage.clear();
  reloadGamePrefs();
});

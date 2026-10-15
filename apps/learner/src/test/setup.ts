import "@testing-library/jest-dom/vitest";
import { reloadGamePrefs } from "../lib/game";
import { forgetSound } from "../lib/sound";

// jsdom draws nothing: a canvas has no context unless a test gives it one
HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext;

// jsdom has no PointerEvent, so a finger's clientX and clientY would be lost:
// a mouse event carries them, as a browser's pointer event does
if (typeof window.PointerEvent === "undefined") {
  class PointerEvent extends MouseEvent {
    pointerId: number;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
    }
  }
  window.PointerEvent = PointerEvent as unknown as typeof window.PointerEvent;
}

afterEach(() => {
  window.localStorage.clear();
  // game touches are this device's own: every test starts with the default, and no sound of its own
  reloadGamePrefs();
  forgetSound();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

import "@testing-library/jest-dom/vitest";

// jsdom draws nothing: a canvas has no context unless a test gives it one
HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext;

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

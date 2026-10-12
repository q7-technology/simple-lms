import { useCallback, useEffect, useState } from "react";

/** Load something from the API, again whenever deps change or reload() is called.
 * Only the latest answer is kept, so a slow one can't overwrite a newer one. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    setError(null);
    load().then((d) => { if (live) setData(d); },
                (e) => { if (live) setError((e as Error).message); });
    return () => { live = false; };
  }, [...deps, n]);
  const reload = useCallback(() => setN((x) => x + 1), []);
  return { data, error, reload };
}

/** Run a change against the API, one at a time, keeping its error to show. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (fn: () => Promise<unknown>): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, run };
}

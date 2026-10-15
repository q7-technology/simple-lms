/** Where keyboard focus goes when a screen's drawer closes, as in Simple
 * WMS. The classroom isn't drawn while a drawer is open, so the desk or
 * person that opened it is remembered by its data-return-focus key. */

let opener: string | null = null;
let drawerClosed = false;

export function rememberOpener(key: string | null): void {
  opener = key;
}

export function noteDrawerClosed(): void {
  drawerClosed = true;
}

/** Once, as the classroom comes back: the opener's key, or null for its
 * heading. Undefined when it isn't coming back from a drawer. */
export function takeReturnFocus(): string | null | undefined {
  if (!drawerClosed) return undefined;
  drawerClosed = false;
  const key = opener;
  opener = null;
  return key;
}

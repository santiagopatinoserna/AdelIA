// "Hide for now" for the capability showcase on the agent home.
//
// One flag in sessionStorage (per tab), whose VALUE is the signed-in user's
// id: the showcase comes back for anyone else who signs in on the same tab,
// and the sign-in page clears it so a re-login always starts with the grid.
// Storage is never allowed to break a render (private mode, blocked storage,
// previews): every access is guarded and falls back to "not hidden".
export const SHOWCASE_HIDDEN_KEY = "adelia:showcase:hidden";

export function readShowcaseHidden(userId: string): boolean {
  try {
    return window.sessionStorage.getItem(SHOWCASE_HIDDEN_KEY) === userId;
  } catch {
    return false;
  }
}

export function writeShowcaseHidden(userId: string, hidden: boolean): void {
  try {
    if (hidden) window.sessionStorage.setItem(SHOWCASE_HIDDEN_KEY, userId);
    else window.sessionStorage.removeItem(SHOWCASE_HIDDEN_KEY);
  } catch {
    /* no storage: the showcase simply shows again next time */
  }
}

export function clearShowcaseHidden(): void {
  try {
    window.sessionStorage.removeItem(SHOWCASE_HIDDEN_KEY);
  } catch {
    /* nothing stored, nothing to clear */
  }
}

// The question a mother typed on the landing, carried to the panel (2026-11-06).
//
// The landing signs her in as a guest and navigates to /dashboard?ask=<key>;
// the text waits under that key in this tab's sessionStorage, never in the
// URL, so a health question does not end up in server logs or the browser's
// history. The panel takes it ONCE: reading removes it, so a second mount or
// a reload cannot send it again and cost a second answer.

const PREFIX = "adelia:ask:";

// With storage refused (some private modes) the question rides in the key
// itself, "q.<encoded>": worse for privacy, but it is never lost.
const INLINE = "q.";

export function keepLandingQuestion(question: string): string {
  const key = Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
  try {
    sessionStorage.setItem(PREFIX + key, question);
    return key;
  } catch {
    return INLINE + encodeURIComponent(question);
  }
}

export function takeLandingQuestion(key: string): string | null {
  if (key.startsWith(INLINE)) {
    try {
      return decodeURIComponent(key.slice(INLINE.length));
    } catch {
      return null;
    }
  }
  try {
    const value = sessionStorage.getItem(PREFIX + key);
    sessionStorage.removeItem(PREFIX + key);
    return value;
  } catch {
    return null;
  }
}

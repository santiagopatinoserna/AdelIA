// Headers for the web server's own POST /guest (lib/auth.ts, "guest" provider).
// The API's brake on guest creation counts the mother's address, but the call
// comes from this server, so the API would see the web container for everyone.
// Behind Cloudflare the real address is CF-Connecting-IP, which Cloudflare
// overwrites on every request, and the API reads it only where it is told
// Cloudflare is in front (TRUST_CF_CONNECTING_IP, adelia/ratelimit.client_ip).
// X-Forwarded-For is not forwarded: the client writes it. The test-traffic
// marker is (lib/qa-traffic.ts): a guest a test run opens is not a signup.
import { qaHeaders } from "./qa-traffic";

export function guestSignupHeaders(incoming: Headers | undefined | null): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...qaHeaders(incoming),
  };
  const address = incoming?.get("cf-connecting-ip")?.trim();
  if (address) headers["CF-Connecting-IP"] = address.slice(0, 64);
  return headers;
}

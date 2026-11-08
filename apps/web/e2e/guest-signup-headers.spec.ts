import { expect, test } from "@playwright/test";

import { guestSignupHeaders } from "@/lib/guest-signup-headers";

// POST /guest is called by this server (lib/auth.ts, the "guest" provider), so
// the API sees the web container for every mother. Behind Cloudflare the real
// address arrives in CF-Connecting-IP, which Cloudflare overwrites on every
// request; that is the one to forward. X-Forwarded-For is written by the
// client and the API no longer reads it (adelia/ratelimit.client_ip).

test("the guest sign-up forwards the mother's Cloudflare address", () => {
  const incoming = new Headers({ "cf-connecting-ip": "203.0.113.7", "x-forwarded-for": "6.6.6.6" });
  expect(guestSignupHeaders(incoming)).toEqual({
    "Content-Type": "application/json",
    "CF-Connecting-IP": "203.0.113.7",
  });
});

test("without Cloudflare in front nothing about the address is forwarded", () => {
  const incoming = new Headers({ "x-forwarded-for": "6.6.6.6" });
  expect(guestSignupHeaders(incoming)).toEqual({ "Content-Type": "application/json" });
  expect(guestSignupHeaders(undefined)).toEqual({ "Content-Type": "application/json" });
});

test("a guest a test run opens is marked as test traffic, and only with the value 1", () => {
  expect(guestSignupHeaders(new Headers({ "x-adelia-qa": "1" }))).toEqual({
    "Content-Type": "application/json",
    "X-AdelIA-QA": "1",
  });
  expect(guestSignupHeaders(new Headers({ "x-adelia-qa": "yes" }))).toEqual({
    "Content-Type": "application/json",
  });
});

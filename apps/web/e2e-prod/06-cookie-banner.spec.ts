import { test } from "@playwright/test";

// Check 6, reserved: the cookie banner. Another branch is building it
// (2026-11-08). When it lands, replace the fixme with the real check, at
// 390x844 and in es/en/fr like check 1: the banner shows on a first visit,
// "Rechazar" is as easy as "Aceptar", the choice survives a reload, and
// rejecting sends no analytics request. Never send a question from here.

test("6 Banner de cookies", async () => {
  test.fixme(true, "pending: the cookie banner is on another branch");
});

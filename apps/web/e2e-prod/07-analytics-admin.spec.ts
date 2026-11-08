import { test } from "@playwright/test";

// Check 7, reserved: the analytics admin page. Another branch is building it
// (2026-11-08). The suite has no admin credentials and must not get any, so
// when it lands the check is what a visitor and a guest see: the page does
// not open for them (a redirect or a 403/404, whatever that branch decides)
// and leaks no figure. A guest for that has to come from check 2's flow and
// be erased the same way (see 02-guest.spec.ts and README.md).

test("7 Administración de la analítica", async () => {
  test.fixme(true, "pending: the analytics admin page is on another branch");
});

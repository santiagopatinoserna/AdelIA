import { expect, test } from "@playwright/test";

// Regression guard for the "100 moms filling info" UX pass: the things that
// silently break for a mom on a phone — horizontal scroll, iOS focus-zoom
// (inputs < 16px), and unlabeled email entry. Public pages only (no backend).

const MOBILE = { width: 375, height: 812 };

test.describe("mom-forms UX invariants", () => {
  test("no horizontal overflow on phone (landing + signin)", async ({ page }) => {
    await page.setViewportSize(MOBILE);
    for (const path of ["/es", "/es/signin", "/en", "/fr"]) {
      await page.goto(path);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(1);
    }
  });

  test("signin email: 16px font, associated label, email autofill", async ({ page }) => {
    await page.setViewportSize(MOBILE);
    await page.goto("/es/signin");
    const info = await page.evaluate(() => {
      const inp = document.querySelector('input[name="email"]') as HTMLInputElement | null;
      if (!inp) return null;
      const label = inp.id ? document.querySelector(`label[for="${inp.id}"]`) : null;
      return {
        fontSize: parseFloat(getComputedStyle(inp).fontSize),
        hasLabel: !!label,
        autoComplete: inp.getAttribute("autocomplete"),
        type: inp.type,
      };
    });
    expect(info, "email input present").not.toBeNull();
    // <16px triggers iOS Safari auto-zoom on focus
    expect(info!.fontSize, "email font-size (iOS zoom guard)").toBeGreaterThanOrEqual(16);
    expect(info!.hasLabel, "email has an associated <label for>").toBe(true);
    expect(info!.autoComplete).toBe("email");
    expect(info!.type).toBe("email");
  });

  test("no comfortable-tap-target regressions on landing (>=32px)", async ({ page }) => {
    await page.setViewportSize(MOBILE);
    await page.goto("/es");
    const tooSmall = await page.evaluate(() => {
      const out: string[] = [];
      document.querySelectorAll("a,button,input,label,select").forEach((el) => {
        const r = el.getBoundingClientRect();
        // A visually clipped label names its real control; it is not a tap target.
        const srLabel = el.tagName === "LABEL" && r.width <= 1 && r.height <= 1
          && (getComputedStyle(el).clip === "rect(0px, 0px, 0px, 0px)"
            || getComputedStyle(el).clipPath === "inset(50%)");
        if (srLabel) return;
        if (r.width > 0 && r.height > 0 && r.height < 32 && (el as HTMLElement).offsetParent !== null) {
          out.push(`${r.height|0}px ${el.tagName}`);
        }
      });
      return out;
    });
    expect(tooSmall, `sub-32px tap targets: ${tooSmall.join(", ")}`).toEqual([]);
  });
});

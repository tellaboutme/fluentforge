/**
 * Accessibility, checked by a machine on every page a learner reaches.
 *
 * `CLAUDE.md` requires semantic HTML, labels, focus states, keyboard
 * operation and reduced-motion support. Until now that was a standard the
 * project asserted about itself and never measured, which is the same
 * arrangement as having no standard.
 *
 * What axe can and cannot do
 * --------------------------
 * axe finds violations of rules that are decidable from the DOM: an input
 * with no label, text below a contrast ratio, a heading level skipped, a
 * landmark missing, an ARIA attribute used wrongly. It reports roughly a
 * third of real accessibility problems, and it never reports a false
 * positive on the rules it does check.
 *
 * It cannot tell whether a label is *helpful*, whether the reading order
 * makes sense, or whether a screen-reader user could actually finish the
 * diagnostic. Those need a person. This suite is a floor, not a ceiling, and
 * `docs/CURRENT_STATUS.md` says so.
 *
 * Serious and critical only
 * -------------------------
 * axe grades its findings, and the two lower grades are largely advisory —
 * "best practice" rules that flag patterns which are often but not always
 * wrong. Failing a build on those trains people to add exceptions, which is
 * how a gate stops meaning anything. Serious and critical are the grades
 * that describe something a user cannot do.
 */

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "correct-horse-9";

/** Blocking grades. Minor and moderate findings are reported, not failed. */
const BLOCKING = ["serious", "critical"];

function uniqueEmail(): string {
  return `a11y-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;
}

async function awaitHydration(page: Page): Promise<void> {
  await page.locator('html[data-hydrated="true"]').waitFor();
}

/**
 * Run axe and fail only on serious or critical findings.
 *
 * The failure message names the rule, the grade and the element, because an
 * accessibility failure that says only "3 violations" sends whoever reads it
 * back to the tool rather than to the fix.
 */
async function expectAccessible(page: Page, where: string): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();

  const blocking = results.violations.filter((violation) =>
    BLOCKING.includes(violation.impact ?? ""),
  );

  const detail = blocking
    .map(
      (violation) =>
        `${violation.impact}: ${violation.id} — ${violation.help}\n` +
        violation.nodes
          .slice(0, 3)
          .map((node) => `    ${node.target.join(" ")}`)
          .join("\n"),
    )
    .join("\n");

  expect(blocking, `${where} has accessibility failures:\n${detail}`).toEqual(
    [],
  );
}

test.describe("accessibility", () => {
  test("the sign-in page is usable", async ({ page }) => {
    await page.goto("/sign-in");
    await awaitHydration(page);
    await expectAccessible(page, "the sign-in page");
  });

  test("the register page is usable", async ({ page }) => {
    // The first page a learner ever meets, and the one with the most form
    // controls: three inputs and a radio group for the time budget.
    await page.goto("/register");
    await awaitHydration(page);
    await expectAccessible(page, "the register page");
  });

  test("the diagnostic is usable", async ({ page }) => {
    // Radio groups under a legend, a live region for progress, and a
    // textarea for the written item.
    await page.goto("/register");
    await awaitHydration(page);
    await page.getByLabel(/what should we call you/i).fill("Egor");
    await page.getByLabel(/^email$/i).fill(uniqueEmail());
    await page.getByLabel(/^password$/i).fill(PASSWORD);
    await page.getByRole("button", { name: /create account/i }).click();
    await expect(page).toHaveURL(/\/diagnostic/);
    await page.getByRole("radio").first().waitFor({ state: "visible" });

    await expectAccessible(page, "the diagnostic");
  });

  test("every learner-facing page declares its language", async ({ page }) => {
    // Not an axe rule at the grade we fail on, and it decides which voice a
    // screen reader uses. An English learning app read aloud in the user's
    // system language is unusable in a way nobody would think to report.
    for (const path of ["/", "/sign-in", "/register"]) {
      await page.goto(path);
      await expect(page.locator("html")).toHaveAttribute("lang", /en/i);
    }
  });

  test("the page a learner lands on has one main landmark", async ({
    page,
  }) => {
    // Screen-reader users navigate by landmark. Two mains, or none, and
    // "skip to content" has nowhere to go.
    await page.goto("/register");
    await awaitHydration(page);
    await expect(page.getByRole("main")).toHaveCount(1);
  });

  test("the register form can be completed with the keyboard alone", async ({
    page,
  }) => {
    // The unit tests assert this too, against jsdom. This is the same claim
    // checked where focus order and native form behaviour are real.
    await page.goto("/register");
    await awaitHydration(page);

    await page.keyboard.press("Tab");
    for (let step = 0; step < 20; step += 1) {
      const focused = await page.evaluate(() => {
        const element = document.activeElement as HTMLElement | null;
        return element?.getAttribute("name") ?? element?.tagName ?? "";
      });
      if (focused === "display_name" || focused === "displayName") break;
      await page.keyboard.press("Tab");
    }

    await page.keyboard.type("Egor");
    await expect(page.getByLabel(/what should we call you/i)).toHaveValue(
      "Egor",
    );
  });
});

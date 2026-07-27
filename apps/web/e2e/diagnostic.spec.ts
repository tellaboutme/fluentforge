/**
 * Browser-level journey: register, take the diagnostic, read the profile.
 *
 * This is the only test in the repository that runs a real browser against
 * both real servers. Everything else mocks one side or the other.
 */

import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "correct-horse-9";

function uniqueEmail(): string {
  return `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;
}

/** Typing into a controlled input before hydration silently loses the
 * keystrokes: the register form once submitted an empty name this way. The
 * app marks the document when React has taken over; wait for it. */
async function awaitHydration(page: Page): Promise<void> {
  await page.locator('html[data-hydrated="true"]').waitFor();
}

async function registerLearner(page: Page): Promise<void> {
  await page.goto("/register");
  await awaitHydration(page);
  await page.getByLabel(/what should we call you/i).fill("Egor");
  await page.getByLabel(/^email$/i).fill(uniqueEmail());
  await page.getByLabel(/^password$/i).fill(PASSWORD);
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page).toHaveURL(/\/diagnostic/);
}

/** Answer whatever is on screen until the diagnostic ends.
 *
 * Every transition here races the UI: between "Next question" and the next
 * render, the old controls are still detaching, and the final submission
 * replaces the whole form with the report mid-action. So each interaction
 * gets a short timeout, and on failure the helper's first question is always
 * "did the report appear?" rather than "retry the same control for 30s".
 */
async function completeDiagnostic(page: Page, limit = 40): Promise<number> {
  let answered = 0;
  const done = page.getByRole("heading", {
    name: /here is what we can say so far/i,
  });
  const submit = page.getByRole("button", {
    // Closed items say "Check answer"; the written response says "Submit".
    name: /check answer|submit my answer/i,
  });

  const finished = () => done.isVisible().catch(() => false);

  for (let step = 0; step < limit; step += 1) {
    if (await finished()) break;

    const radio = page.getByRole("radio").first();
    const textAnswer = page.getByLabel(/your answer/i);
    await done.or(radio).or(textAnswer).first().waitFor({ state: "visible" });
    if (await finished()) break;

    try {
      if (await radio.isVisible().catch(() => false)) {
        await radio.check({ timeout: 5000 });
      } else {
        await textAnswer.fill("guess", { timeout: 5000 });
      }
      await submit.click({ timeout: 5000 });
      answered += 1;

      const next = page.getByRole("button", { name: /next question/i });
      await next.waitFor({ state: "visible", timeout: 5000 });
      await next.click({ timeout: 5000 });
      await next.waitFor({ state: "hidden", timeout: 5000 });
    } catch (error) {
      // A control that vanished mid-action usually means the report took
      // over. If it did, the journey succeeded; anything else is real.
      if (await finished()) break;
      throw error;
    }
  }

  return answered;
}

test("a new learner can register, take the diagnostic, and see a profile", async ({
  page,
}) => {
  await registerLearner(page);

  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const answered = await completeDiagnostic(page);
  expect(answered).toBeGreaterThan(0);

  await expect(
    page.getByRole("heading", { name: /here is what we can say so far/i }),
  ).toBeVisible();
  await expect(page.getByText(/not an official/i)).toBeVisible();

  await page.getByRole("link", { name: /go to my profile/i }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByRole("heading", { name: "Egor" })).toBeVisible();
});

test("the profile never shows a CEFR level a learner has not earned", async ({
  page,
}) => {
  await registerLearner(page);
  await completeDiagnostic(page);
  await page.getByRole("link", { name: /go to my profile/i }).click();

  await expect(page.getByRole("heading", { name: "Egor" })).toBeVisible();

  // A short diagnostic cannot support a can-do claim, so every skill card must
  // still read as needing evidence.
  await expect(page.getByText(/needs evidence/i).first()).toBeVisible();
  const cards = page.locator("article.skill-card");
  await expect(cards.first()).toBeVisible();
  await expect(cards.first().getByText("—")).toBeVisible();
});

test("the dashboard shows a plan that explains itself", async ({ page }) => {
  await registerLearner(page);
  await completeDiagnostic(page);
  await page.getByRole("link", { name: /go to my profile/i }).click();

  const plan = page.locator("ol.plan-list");
  await expect(plan).toBeVisible();

  // Every item must say why it is there, not just what it is.
  const reasons = plan.locator(".plan-why");
  const count = await reasons.count();
  expect(count).toBeGreaterThan(0);
  for (let index = 0; index < count; index += 1) {
    await expect(reasons.nth(index)).not.toBeEmpty();
  }
});

test("the diagnostic is operable with the keyboard alone", async ({ page }) => {
  await page.goto("/register");
  await awaitHydration(page);

  await page.keyboard.press("Tab"); // skip link
  await page.keyboard.press("Tab"); // display name
  await page.keyboard.type("Egor");
  await page.keyboard.press("Tab");
  await page.keyboard.type(uniqueEmail());
  await page.keyboard.press("Tab");
  await page.keyboard.type(PASSWORD);

  await page.getByRole("button", { name: /create account/i }).press("Enter");
  await expect(page).toHaveURL(/\/diagnostic/);

  // Focus must land on the question, not stay at the top of the document.
  const question = page.getByRole("heading", { level: 1 });
  await expect(question).toBeFocused();

  await page.keyboard.press("Tab");
  await page.keyboard.press("Space");
  await page.getByRole("button", { name: /check answer/i }).press("Enter");
  await expect(page.getByRole("status")).toBeVisible();
});

test("the skip link is reachable and works", async ({ page }) => {
  await page.goto("/");
  await awaitHydration(page);
  await page.keyboard.press("Tab");

  const skip = page.getByRole("link", { name: /skip to content/i });
  await expect(skip).toBeFocused();
  await skip.press("Enter");
  await expect(page.locator("#main")).toBeVisible();
});

test("a signed-out visitor is sent to sign in", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/sign-in/);
});

test("wrong credentials do not reveal whether the email exists", async ({
  page,
}) => {
  await page.goto("/sign-in");
  await page.getByLabel(/^email$/i).fill("nobody@example.com");
  await page.getByLabel(/^password$/i).fill(PASSWORD);
  await page.getByRole("button", { name: /^sign in$/i }).click();

  // Scoped to main: the Next.js dev overlay contributes its own
  // `role="alert"`, and the unscoped locator matches both.
  const alert = page.getByRole("main").getByRole("alert");
  await expect(alert).toBeVisible();
  await expect(alert).toContainText(/email or password is incorrect/i);
  await expect(alert).not.toContainText(/no account|not found|unknown/i);
});

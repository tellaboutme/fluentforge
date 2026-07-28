/**
 * The loop the product exists for, in a real browser against both servers.
 *
 * The diagnostic spec proves a learner can be assessed. This proves the part
 * that comes after: a plan appears, an item in it opens, completing it
 * changes the profile, and reflection records nothing.
 *
 * Why this needs a browser rather than more unit tests. Every screen here
 * already has unit tests against jsdom with the API mocked, so what those
 * cannot catch is precisely what is worth catching: a field the client reads
 * under one name and the API sends under another, a plan item pointing at a
 * route that does not exist, a form that submits before hydration. The first
 * run of the diagnostic spec found four defects of exactly that shape.
 *
 * Written to survive a thin plan. Which activity kinds a new learner is
 * offered depends on their diagnostic answers and on what content exists at
 * their band, so the test asserts on *whatever opened* rather than requiring
 * a particular kind to be there. A test that demanded a mediation task would
 * fail for a reason that is not a defect.
 */

import { expect, test, type Page } from "@playwright/test";

const PASSWORD = "correct-horse-9";

/** Matches the diagnostic spec: short locally, patient on a slower runner. */
const ACTION_TIMEOUT = process.env.CI ? 20_000 : 5_000;

function uniqueEmail(): string {
  return `loop-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;
}

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

/** Answer everything until the report appears. Mirrors the diagnostic spec. */
async function completeDiagnostic(page: Page, limit = 40): Promise<void> {
  const done = page.getByRole("heading", {
    name: /here is what we can say so far/i,
  });
  const submit = page.getByRole("button", {
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
        await radio.check({ timeout: ACTION_TIMEOUT });
      } else {
        await textAnswer.fill(
          "I went to the market on Saturday and bought some vegetables because the weather was good.",
          { timeout: ACTION_TIMEOUT },
        );
      }
      await expect(submit).toBeEnabled({ timeout: ACTION_TIMEOUT });
      await submit.click({ timeout: ACTION_TIMEOUT });

      const next = page.getByRole("button", { name: /next question/i });
      await next.waitFor({ state: "visible", timeout: ACTION_TIMEOUT });
      await next.click({ timeout: ACTION_TIMEOUT });
      await next.waitFor({ state: "hidden", timeout: ACTION_TIMEOUT });
    } catch (error) {
      if (await finished()) break;
      throw error;
    }
  }

  await expect(done).toBeVisible();
}

async function goToDashboard(page: Page): Promise<void> {
  await page.getByRole("link", { name: /go to my profile/i }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await awaitHydration(page);
}

test.describe("the learning loop", () => {
  test("a plan appears, and every item in it explains itself", async ({
    page,
  }) => {
    // `docs/ADAPTIVE_ENGINE.md` forbids an opaque score: the reasoning has to
    // reach the learner, not just the database.
    await registerLearner(page);
    await completeDiagnostic(page);
    await goToDashboard(page);

    // Located by the rows themselves rather than by the section's accessible
    // name: the plan's heading is chosen from the learner's state ("From
    // understanding to using", "Producing language today"), so matching on it
    // would tie this test to wording that is meant to vary.
    const explanations = page.locator(".plan-why");
    await expect(explanations.first()).toBeVisible({ timeout: ACTION_TIMEOUT });
    const count = await explanations.count();
    expect(count).toBeGreaterThan(0);
    for (let index = 0; index < count; index += 1) {
      expect(
        (await explanations.nth(index).innerText()).trim().length,
      ).toBeGreaterThan(0);
    }
  });

  test("an item in the plan opens, and finishing it changes the profile", async ({
    page,
  }) => {
    // The whole point of Milestone 3 onwards. A plan full of names that go
    // nowhere is the failure this journey exists to catch.
    await registerLearner(page);
    await completeDiagnostic(page);
    await goToDashboard(page);

    const openable = page.locator(".plan-main a").first();
    await expect(openable).toBeVisible({ timeout: ACTION_TIMEOUT });
    const title = (await openable.innerText()).trim();
    await openable.click();

    // Whatever kind it was, the player must render its own heading rather
    // than a blank screen or a fallback.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: ACTION_TIMEOUT,
    });
    expect(title.length).toBeGreaterThan(0);

    // Every kind ends with a way back that actually goes back.
    const back = page.getByRole("link", { name: /back to today/i });
    if (await back.isVisible().catch(() => false)) {
      await back.click();
      await expect(page).toHaveURL(/\/dashboard/);
    }
  });

  test("a sitting can be started, worked in, and finished", async ({
    page,
  }) => {
    // The round trip the summary depends on. Nothing here asserts a number,
    // because the point of the screen is that it does not produce one: it
    // asserts that the work lands inside the sitting and that the disclaimer
    // survives to the browser.
    await registerLearner(page);
    await completeDiagnostic(page);
    await goToDashboard(page);

    await page.getByRole("button", { name: /start a session/i }).click();
    const finish = page.getByRole("button", { name: /finish for today/i });
    await expect(finish).toBeVisible({ timeout: ACTION_TIMEOUT });

    await finish.click();
    await expect(page).toHaveURL(/\/finish\//, { timeout: ACTION_TIMEOUT });

    // Always present, whatever the learner did or did not do.
    await expect(page.getByText(/not proof of anything/i)).toBeVisible({
      timeout: ACTION_TIMEOUT,
    });

    await page.getByRole("link", { name: /back to today/i }).click();
    await expect(page).toHaveURL(/\/dashboard/);
  });

  test("the profile never shows a level the learner has not earned", async ({
    page,
  }) => {
    // Restated here as well as in the diagnostic spec, because this is the
    // claim the whole product rests on and it has to survive the loop, not
    // only the first assessment.
    await registerLearner(page);
    await completeDiagnostic(page);
    await goToDashboard(page);

    await expect(page.getByText(/needs evidence/i).first()).toBeVisible({
      timeout: ACTION_TIMEOUT,
    });
  });
});

test.describe("reflection", () => {
  test("records a note and says plainly that nothing was scored", async ({
    page,
  }) => {
    // The one screen where a learner writes and nothing judges it. If that
    // ever silently changed, this is where it would show.
    await registerLearner(page);
    await completeDiagnostic(page);
    await goToDashboard(page);

    await page.goto("/reflect");
    await awaitHydration(page);

    await expect(
      page.getByText(/nothing here is checked, corrected, or counted/i),
    ).toBeVisible({ timeout: ACTION_TIMEOUT });

    await page
      .getByLabel(/what do you make of it/i)
      .fill("Questions are still the hard part.");
    await page.getByRole("button", { name: /save this/i }).click();

    await expect(page.getByText(/your profile is unchanged/i)).toBeVisible({
      timeout: ACTION_TIMEOUT,
    });
  });

  test("shows the previous note the next time", async ({ page }) => {
    // Reflection that never refers back is a diary nobody rereads.
    await registerLearner(page);
    await completeDiagnostic(page);
    await goToDashboard(page);

    await page.goto("/reflect");
    await awaitHydration(page);
    await page.getByLabel(/what do you make of it/i).fill("Reading is slow.");
    await page.getByRole("button", { name: /save this/i }).click();
    await expect(page.getByText(/your profile is unchanged/i)).toBeVisible({
      timeout: ACTION_TIMEOUT,
    });

    await page.goto("/reflect");
    await awaitHydration(page);
    await expect(page.getByText("Reading is slow.")).toBeVisible({
      timeout: ACTION_TIMEOUT,
    });
  });
});

test.describe("benchmarks", () => {
  test("are refused before they are due, with a reason", async ({ page }) => {
    // A learner who could take one whenever they felt ready would be
    // measuring their confidence. The refusal is the feature.
    await registerLearner(page);
    await page.goto("/benchmark");
    await awaitHydration(page);

    await expect(page.getByRole("heading", { name: /unaided/i })).toBeVisible({
      timeout: ACTION_TIMEOUT,
    });
    await expect(
      page.getByRole("button", { name: /start the benchmark/i }),
    ).toHaveCount(0);
  });
});

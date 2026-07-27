import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end configuration.
 *
 * Both servers are started by Playwright against a throwaway SQLite database,
 * so the suite needs no manual setup and leaves no state behind.
 *
 * Requires browser binaries: `pnpm exec playwright install --with-deps chromium`.
 */
const API_PORT = 8001;
const WEB_PORT = 3001;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",

  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "on-first-retry",
  },

  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    // A real phone viewport: the mobile layout is a stated requirement.
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],

  webServer: [
    {
      // Python, not bash: on a Windows dev machine `bash` resolves to WSL,
      // and a broken WSL failed the suite before a single test ran.
      command: "uv run python ../../scripts/e2e_api.py",
      port: API_PORT,
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: `pnpm exec next dev --port ${WEB_PORT}`,
      port: WEB_PORT,
      reuseExistingServer: !process.env.CI,
      env: { NEXT_PUBLIC_API_URL: `http://127.0.0.1:${API_PORT}` },
    },
  ],
});

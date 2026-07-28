/**
 * Your data: taking a copy, and destroying it.
 *
 * Two properties matter more than the mechanics.
 *
 * **The warning to export first appears before the delete button**, and stops
 * appearing once they have. Someone who arrived here intending to delete
 * needs that while it can still help them; telling them afterwards would be
 * technically true and useless.
 *
 * **Deleting takes deliberate effort and no more.** The password and a typed
 * phrase — a checkbox is one stray click. But the phrase is forgiving about
 * case and whitespace, because it exists to stop an accident, not to test
 * someone's typing at the worst possible moment.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "@/lib/session";
import { routerMock } from "@/test/setup";

import AccountPage from "./page";

const mocks = vi.hoisted(() => ({
  downloadExport: vi.fn(),
  deleteAccount: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...mocks,
}));

vi.mock("next/navigation", async () => {
  const setup = await import("@/test/setup");
  return { useRouter: () => setup.routerMock };
});

function renderPage() {
  window.sessionStorage.setItem("fluentforge.session", "test-token");
  return render(
    <SessionProvider>
      <AccountPage />
    </SessionProvider>,
  );
}

beforeEach(() => {
  mocks.downloadExport.mockReset();
  mocks.deleteAccount.mockReset();
  mocks.downloadExport.mockResolvedValue(undefined);
  mocks.deleteAccount.mockResolvedValue(undefined);
});

describe("taking a copy", () => {
  it("says what the file contains", async () => {
    renderPage();

    expect(
      await screen.findByText(/every observation behind your profile/i),
    ).toBeInTheDocument();
  });

  it("says the file admits its own gaps", async () => {
    // The property the export was built around: an export that silently
    // omits something invites you to think you got everything.
    renderPage();

    expect(
      screen.getByText(/what was never collected from what was left out/i),
    ).toBeInTheDocument();
  });

  it("downloads on request", async () => {
    renderPage();

    await userEvent.click(
      screen.getByRole("button", { name: /download my data/i }),
    );

    expect(mocks.downloadExport).toHaveBeenCalledWith("test-token");
  });
});

describe("the warning to export first", () => {
  it("appears before the delete control, not after it", async () => {
    renderPage();

    const warning = screen.getByText(/download your data first/i);
    const control = screen.getByRole("button", { name: /delete my account/i });

    expect(
      warning.compareDocumentPosition(control) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("stops nagging once they have exported", async () => {
    renderPage();

    await userEvent.click(
      screen.getByRole("button", { name: /download my data/i }),
    );

    expect(screen.queryByText(/download your data first/i)).toBeNull();
  });
});

describe("deleting", () => {
  it("does not show the form until asked", () => {
    renderPage();

    expect(screen.queryByLabelText(/your password/i)).toBeNull();
  });

  it("says plainly that it cannot be undone", () => {
    renderPage();

    expect(
      screen.getByText(/cannot be undone and we cannot get any of it back/i),
    ).toBeInTheDocument();
  });

  it("needs the password and the typed phrase", async () => {
    renderPage();

    await userEvent.click(
      screen.getByRole("button", { name: /delete my account/i }),
    );
    await userEvent.type(screen.getByLabelText(/your password/i), "hunter2");
    await userEvent.type(
      screen.getByLabelText(/to confirm/i),
      "delete my account",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /delete everything/i }),
    );

    expect(mocks.deleteAccount).toHaveBeenCalledWith("test-token", {
      password: "hunter2",
      confirm: "delete my account",
    });
  });

  it("signs out and leaves, so nothing points at an account that is gone", async () => {
    renderPage();

    await userEvent.click(
      screen.getByRole("button", { name: /delete my account/i }),
    );
    await userEvent.type(screen.getByLabelText(/your password/i), "hunter2");
    await userEvent.type(
      screen.getByLabelText(/to confirm/i),
      "delete my account",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /delete everything/i }),
    );

    expect(window.sessionStorage.getItem("fluentforge.session")).toBeNull();
    expect(routerMock.replace).toHaveBeenCalledWith("/");
  });

  it("can be backed out of", async () => {
    renderPage();

    await userEvent.click(
      screen.getByRole("button", { name: /delete my account/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(screen.queryByLabelText(/your password/i)).toBeNull();
    expect(mocks.deleteAccount).not.toHaveBeenCalled();
  });

  it("keeps the learner here when the server refuses", async () => {
    // A wrong password must not look like it worked.
    mocks.deleteAccount.mockRejectedValue(new Error("wrong password"));
    renderPage();

    await userEvent.click(
      screen.getByRole("button", { name: /delete my account/i }),
    );
    await userEvent.type(screen.getByLabelText(/your password/i), "wrong");
    await userEvent.type(
      screen.getByLabelText(/to confirm/i),
      "delete my account",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /delete everything/i }),
    );

    expect(routerMock.replace).not.toHaveBeenCalledWith("/");
    expect(window.sessionStorage.getItem("fluentforge.session")).toBe(
      "test-token",
    );
  });
});

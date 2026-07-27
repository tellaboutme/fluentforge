/**
 * Registration screen.
 *
 * Driven through accessible names and keyboard interaction, so the tests fail
 * if a field loses its label or an error stops being announced — the things
 * `docs/DEFINITION_OF_DONE.md` requires and that a snapshot would not catch.
 */

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { SessionProvider } from "@/lib/session";
import { routerMock } from "@/test/setup";

import RegisterPage from "./page";

const registerMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  register: registerMock,
}));

function renderPage() {
  return render(
    <SessionProvider>
      <RegisterPage />
    </SessionProvider>,
  );
}

beforeEach(() => {
  registerMock.mockReset();
});

describe("accessibility", () => {
  it("labels every field", () => {
    renderPage();
    expect(
      screen.getByLabelText(/what should we call you/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
  });

  it("groups the time choice under a legend", () => {
    renderPage();
    expect(
      screen.getByRole("group", { name: /how long can you practise/i }),
    ).toBeInTheDocument();
  });

  it("describes the password rule before anything goes wrong", () => {
    renderPage();
    expect(screen.getByLabelText(/^password$/i)).toHaveAccessibleDescription(
      /at least 10 characters/i,
    );
  });

  it("offers a default practice length so the form is submittable as-is", () => {
    renderPage();
    expect(screen.getByRole("radio", { name: /40 minutes/i })).toBeChecked();
  });
});

describe("submitting", () => {
  it("can be completed with the keyboard alone", async () => {
    const user = userEvent.setup();
    registerMock.mockResolvedValue({ accessToken: "tok", expiresIn: 60 });
    renderPage();

    await user.tab();
    await user.keyboard("Egor");
    await user.tab();
    await user.keyboard("egor@example.com");
    await user.tab();
    await user.keyboard("correct-horse-9");

    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => expect(registerMock).toHaveBeenCalledTimes(1));
    expect(registerMock).toHaveBeenCalledWith({
      displayName: "Egor",
      email: "egor@example.com",
      password: "correct-horse-9",
      dailyMinutes: 40,
    });
  });

  it("sends the learner to the diagnostic on success", async () => {
    const user = userEvent.setup();
    registerMock.mockResolvedValue({ accessToken: "tok", expiresIn: 60 });
    renderPage();

    await fill(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() =>
      expect(routerMock.push).toHaveBeenCalledWith("/diagnostic"),
    );
  });

  it("shows a busy state so the button cannot be double-submitted", async () => {
    const user = userEvent.setup();
    let release: (value: unknown) => void = () => {};
    registerMock.mockReturnValue(new Promise((resolve) => (release = resolve)));
    renderPage();

    await fill(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    const busy = await screen.findByRole("button", {
      name: /creating your account/i,
    });
    expect(busy).toBeDisabled();

    // Settle inside act so the resulting state update is not reported as an
    // unwrapped update after the test ends.
    await act(async () => {
      release({ accessToken: "tok", expiresIn: 60 });
    });
  });
});

describe("errors", () => {
  it("announces a weak password and marks the field invalid", async () => {
    const user = userEvent.setup();
    registerMock.mockRejectedValue(
      new ApiError(
        422,
        "weak_password",
        "Password must be at least 10 characters.",
        {
          min_length: 10,
        },
      ),
    );
    renderPage();

    await fill(user, { password: "short" });
    await user.click(screen.getByRole("button", { name: /create account/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/at least 10 characters/i);
    expect(screen.getByLabelText(/^password$/i)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("offers a route out when the email is taken", async () => {
    const user = userEvent.setup();
    registerMock.mockRejectedValue(
      new ApiError(
        409,
        "email_already_registered",
        "An account already exists.",
      ),
    );
    renderPage();

    await fill(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await screen.findByRole("alert");
    expect(screen.getByLabelText(/^email$/i)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(
      screen.getByRole("link", { name: /sign in instead/i }),
    ).toHaveAttribute("href", "/sign-in");
  });

  it("explains how to start the API when it cannot be reached", async () => {
    const user = userEvent.setup();
    registerMock.mockRejectedValue(
      new ApiError(0, "network_unavailable", "Could not reach the server."),
    );
    renderPage();

    await fill(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/make api/i);
  });

  it("does not navigate when registration fails", async () => {
    const user = userEvent.setup();
    registerMock.mockRejectedValue(
      new ApiError(409, "email_already_registered", "x"),
    );
    renderPage();

    await fill(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await screen.findByRole("alert");
    expect(routerMock.push).not.toHaveBeenCalled();
  });
});

async function fill(
  user: ReturnType<typeof userEvent.setup>,
  overrides: { password?: string } = {},
) {
  await user.type(screen.getByLabelText(/what should we call you/i), "Egor");
  await user.type(screen.getByLabelText(/^email$/i), "egor@example.com");
  await user.type(
    screen.getByLabelText(/^password$/i),
    overrides.password ?? "correct-horse-9",
  );
}

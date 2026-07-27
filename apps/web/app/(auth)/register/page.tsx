"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ApiError, register } from "@/lib/api";
import { useSession } from "@/lib/session";
import { ErrorNotice } from "@/components/Status";

const MINUTE_OPTIONS = [20, 40, 60];

export default function RegisterPage() {
  const router = useRouter();
  const { signIn } = useSession();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [dailyMinutes, setDailyMinutes] = useState(40);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await register({
        email,
        password,
        displayName,
        dailyMinutes,
      });
      signIn(result.accessToken);
      router.push("/diagnostic");
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  const apiError = error instanceof ApiError ? error : null;
  const weakPassword = apiError?.code === "weak_password";
  const emailTaken = apiError?.code === "email_already_registered";
  const minLength = Number(apiError?.details?.min_length ?? 10);

  return (
    <main id="main" className="narrow">
      <h1 className="page-title">Create your account</h1>
      <p className="muted">
        Everything is stored on your own machine. No AI key is needed to start.
      </p>

      <form onSubmit={onSubmit} noValidate>
        {error ? <ErrorNotice error={error} /> : null}

        <div className="field">
          <label htmlFor="displayName">What should we call you?</label>
          <input
            id="displayName"
            name="displayName"
            type="text"
            autoComplete="name"
            required
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </div>

        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            aria-invalid={emailTaken}
            aria-describedby={emailTaken ? "email-hint" : undefined}
          />
          {emailTaken ? (
            <p id="email-hint" className="field-error">
              That email is already registered.{" "}
              <Link href="/sign-in">Sign in instead</Link>.
            </p>
          ) : null}
        </div>

        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-invalid={weakPassword}
            aria-describedby="password-hint"
          />
          <p
            id="password-hint"
            className={weakPassword ? "field-error" : "hint"}
          >
            {weakPassword
              ? apiError.message
              : `At least ${minLength} characters, using at least 4 different ones.`}
          </p>
        </div>

        <fieldset className="field">
          <legend>How long can you practise on a normal day?</legend>
          <div className="choices">
            {MINUTE_OPTIONS.map((minutes) => (
              <label key={minutes} className="choice">
                <input
                  type="radio"
                  name="dailyMinutes"
                  value={minutes}
                  checked={dailyMinutes === minutes}
                  onChange={() => setDailyMinutes(minutes)}
                />
                <span>{minutes} minutes</span>
              </label>
            ))}
          </div>
          <p className="hint">You can change this at any time.</p>
        </fieldset>

        <button type="submit" disabled={busy}>
          {busy ? "Creating your account…" : "Create account"}
        </button>
      </form>

      <p className="muted">
        Already have an account? <Link href="/sign-in">Sign in</Link>.
      </p>
    </main>
  );
}

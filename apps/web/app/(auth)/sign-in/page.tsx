"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { ApiError, login } from "@/lib/api";
import { useSession } from "@/lib/session";
import { ErrorNotice } from "@/components/Status";

export default function SignInPage() {
  const router = useRouter();
  const { signIn } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await login({ email, password });
      signIn(result.accessToken);
      router.push("/dashboard");
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  const invalidCredentials =
    error instanceof ApiError && error.code === "invalid_credentials";

  return (
    <main id="main" className="narrow">
      <h1 className="page-title">Sign in</h1>

      <form onSubmit={onSubmit} noValidate>
        {error ? <ErrorNotice error={error} /> : null}

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
            aria-invalid={invalidCredentials}
          />
        </div>

        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-invalid={invalidCredentials}
          />
        </div>

        <button type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p className="muted">
        No account yet? <Link href="/register">Create one</Link>.
      </p>
    </main>
  );
}

"use client";

import type { ReactNode } from "react";

import { ApiError } from "@/lib/api";

/**
 * Shared loading, empty, and error states.
 *
 * Every screen must handle all of them (`docs/DEFINITION_OF_DONE.md`), so they
 * live here rather than being reinvented per page.
 */

export function Loading({ label }: { label: string }) {
  return (
    <p className="state" role="status" aria-live="polite">
      {label}
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="state">{children}</p>;
}

export function ErrorNotice({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const apiError = error instanceof ApiError ? error : null;
  const message =
    apiError?.message ??
    (error instanceof Error ? error.message : "Something went wrong.");

  return (
    <div className="notice notice-error" role="alert">
      <p>{message}</p>
      {apiError?.code === "curriculum_not_loaded" ? (
        <p className="hint">
          The server has no curriculum loaded yet. Run{" "}
          <code>make load-curriculum</code>.
        </p>
      ) : null}
      {apiError?.code === "network_unavailable" ? (
        <p className="hint">
          Is the API running? Start it with <code>make api</code>.
        </p>
      ) : null}
      {onRetry && (apiError === null || apiError.isTransient) ? (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
      {apiError?.requestId ? (
        <p className="hint">Reference: {apiError.requestId}</p>
      ) : null}
    </div>
  );
}

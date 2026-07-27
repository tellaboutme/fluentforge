"use client";

import { useSyncExternalStore } from "react";

/**
 * Whether the browser thinks it has a network.
 *
 * `navigator.onLine` is weak evidence: it reports whether an interface is up,
 * not whether the API is reachable, so it says `true` on a captive portal and
 * on a connection that drops every packet. It is used here for one thing —
 * deciding whether to *try* — and never as proof that a request will succeed.
 * A failed request is what actually establishes that the server is out of
 * reach, and `ApiError` with `network_unavailable` already carries that.
 *
 * `useSyncExternalStore` rather than an effect, so the value is right on the
 * first render on the client and hydration-safe on the server: the server has
 * no network state to report, and guessing "offline" there would flash a
 * warning at every learner on every page load.
 */

function subscribe(onChange: () => void): () => void {
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

function readOnline(): boolean {
  return typeof navigator === "undefined" ? true : navigator.onLine;
}

/** Rendered on the server, where there is nothing to report. */
function assumeOnlineOnTheServer(): boolean {
  return true;
}

export function useOnline(): boolean {
  return useSyncExternalStore(subscribe, readOnline, assumeOnlineOnTheServer);
}

/** The same check for non-React callers, e.g. the API client. */
export function isOffline(): boolean {
  return typeof navigator !== "undefined" && navigator.onLine === false;
}

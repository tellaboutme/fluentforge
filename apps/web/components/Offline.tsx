"use client";

import { useEffect } from "react";

import { useOnline } from "@/lib/online";

/**
 * Registers the service worker, and tells the learner what offline means.
 *
 * Both halves are here on purpose: a service worker that caches without
 * saying so is the thing that makes offline support untrustworthy. A learner
 * looking at yesterday's plan and a learner looking at today's need to be
 * able to tell which they are.
 */

/**
 * A banner, shown only while the browser reports no network.
 *
 * It says what still works and what does not, in that order. "You are
 * offline" alone leaves someone guessing whether their half-written essay is
 * about to be lost.
 */
export function OfflineNotice() {
  const online = useOnline();
  if (online) return null;

  return (
    <div className="notice notice-warn offline-banner" role="status">
      <p>
        <strong>You are offline.</strong> You can still read today&rsquo;s plan
        and anything you have already opened.
      </p>
      <p>
        Checking your work needs the server, so nothing you write will be marked
        until you are back. It stays on screen in the meantime.
      </p>
    </div>
  );
}

/**
 * Registers `/sw.js` after the page has settled.
 *
 * Deliberately not during render or in a layout effect. Registration competes
 * with the first paint for the main thread, and a learner opening the app for
 * the first time should not wait on a cache they cannot benefit from yet.
 *
 * Development is excluded: a stale worker serving an old bundle is a
 * genuinely confusing way to lose an afternoon, and offline support is not
 * what anyone is testing at `next dev`.
 */
export function ServiceWorkerRegistration() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;

    const register = () => {
      void navigator.serviceWorker.register("/sw.js").catch(() => {
        // A failed registration costs the learner nothing: the app works
        // exactly as it did before service workers existed. Failing loudly
        // here would report a problem they cannot act on.
      });
    };

    if (document.readyState === "complete") {
      register();
      return;
    }
    window.addEventListener("load", register);
    return () => window.removeEventListener("load", register);
  }, []);

  return null;
}

/**
 * Clears anything cached that belonged to the learner who just signed out.
 *
 * Without this, a shared browser hands the next person a cached profile and
 * plan. The worker owns the deletion because it owns the cache.
 */
export function clearCachedLearnerData(): void {
  if (typeof navigator === "undefined") return;
  navigator.serviceWorker?.controller?.postMessage("clear-learner-data");
}

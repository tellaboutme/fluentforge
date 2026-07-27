/**
 * FluentForge service worker.
 *
 * Milestone 8 asks for offline use. What that can honestly mean here is
 * narrower than "the app works offline", and the shape of this file is the
 * argument for why.
 *
 * Scoring happens on the server. Every activity in the product is checked
 * against curriculum the browser does not have, and evidence is weighted by
 * a mastery model the browser does not run. So a submission cannot be
 * completed offline, and pretending otherwise would mean either scoring
 * against a stale copy of the curriculum or recording evidence with a
 * timestamp the client chose. Neither is acceptable: the first gives the
 * learner a mark the server would not have given, and the second lets any
 * client backdate its own evidence into the review scheduler.
 *
 * What offline can be is **reading**. Today's plan, an activity already
 * opened, the profile: all of it was fetched once and can be shown again.
 *
 * Three rules follow.
 *
 * **Cached API responses are served only while offline.** A cache that
 * answers while the network is up would show a learner yesterday's plan and
 * never tell them. Offline is the one situation where a stale answer beats
 * no answer, and the UI says which one they are looking at.
 *
 * **Nothing but GET is ever cached, and no mutation is ever replayed.** A
 * queued submission that fires later would be scored at a moment the learner
 * was not present for, against a plan that may have moved on.
 *
 * **Authenticated responses are cached in a per-origin cache and cleared on
 * sign-out**, because the alternative is one learner's profile surviving in
 * the cache for the next person to use the browser.
 *
 * Hand-written rather than generated. A generated worker would be larger,
 * would precache things nobody asked it to, and would not carry any of the
 * reasoning above.
 */

const VERSION = "v1";
const SHELL_CACHE = `fluentforge-shell-${VERSION}`;
const DATA_CACHE = `fluentforge-data-${VERSION}`;
const OFFLINE_URL = "/offline";

/** The least that has to be there for the app to render an honest message. */
const SHELL = [OFFLINE_URL, "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL))
      // A shell asset that 404s must not wedge the install. The worker is
      // still useful for everything else it caches at runtime.
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== SHELL_CACHE && key !== DATA_CACHE)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

/** Sign-out clears anything that belonged to the learner who signed out. */
self.addEventListener("message", (event) => {
  if (event.data === "clear-learner-data") {
    event.waitUntil(caches.delete(DATA_CACHE));
  }
});

function isApiRequest(url) {
  return url.pathname.startsWith("/api/");
}

function isImmutableAsset(url) {
  // Next hashes these, so a cached copy can never be the wrong one.
  return (
    url.pathname.startsWith("/_next/static/") ||
    url.pathname.endsWith(".woff2") ||
    url.pathname.endsWith(".svg")
  );
}

self.addEventListener("fetch", (event) => {
  const request = event.request;

  // Never touch a mutation. Not cached, not queued, not replayed.
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  if (isImmutableAsset(url)) {
    event.respondWith(cacheFirst(request, SHELL_CACHE));
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(navigateOrExplain(request));
    return;
  }

  if (isApiRequest(url)) {
    event.respondWith(networkThenCacheWhenOffline(request));
  }
});

async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;

  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(cacheName);
    cache.put(request, response.clone());
  }
  return response;
}

/**
 * A page request. Live when there is a network; the last copy of that page
 * when there is not; and a page that explains the situation when there is
 * neither.
 */
async function navigateOrExplain(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(SHELL_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    const offline = await caches.match(OFFLINE_URL);
    if (offline) return offline;
    return new Response("You are offline.", {
      status: 503,
      headers: { "Content-Type": "text/plain" },
    });
  }
}

/**
 * An API read. The network always wins while it is there.
 *
 * This is the decision worth defending: a cache that answered while online
 * would hand a learner yesterday's plan with nothing on screen to say so.
 * Offline is the only situation where a stale answer beats no answer.
 */
async function networkThenCacheWhenOffline(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(DATA_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    const cached = await caches.match(request, { cacheName: DATA_CACHE });
    if (cached) {
      // Marked so the client can say plainly that this is a saved copy.
      const headers = new Headers(cached.headers);
      headers.set("X-FluentForge-Cached", "1");
      return new Response(cached.body, {
        status: cached.status,
        statusText: cached.statusText,
        headers,
      });
    }
    throw error;
  }
}

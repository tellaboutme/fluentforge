"use client";

/**
 * Authentication session.
 *
 * The token lives in a tiny external store read through `useSyncExternalStore`
 * rather than being copied into component state inside an effect. That keeps
 * server and client renders consistent and avoids the cascading re-render React
 * warns about when an effect sets state synchronously.
 *
 * Storage is `sessionStorage`: a refresh keeps you signed in, closing the
 * browser does not. This is a deliberate interim choice — an httpOnly,
 * SameSite cookie issued by the API is stronger and is planned with deployment
 * hardening, but needs cookie support on the API side that does not exist yet.
 * Recorded in `docs/DECISION_LOG.md`.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

const STORAGE_KEY = "fluentforge.session";

const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function emit(): void {
  for (const listener of listeners) listener();
}

function readToken(): string | null {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    // Private browsing can throw on storage access. Signed-out is a safe
    // fallback and the app stays usable.
    return null;
  }
}

function writeToken(token: string | null): void {
  try {
    if (token === null) window.sessionStorage.removeItem(STORAGE_KEY);
    else window.sessionStorage.setItem(STORAGE_KEY, token);
  } catch {
    /* nothing further to do */
  }
  emit();
}

/** The server has no session storage, so it always renders signed out. */
const serverToken = (): string | null => null;
const serverReady = (): boolean => false;
const clientReady = (): boolean => true;

interface SessionValue {
  token: string | null;
  /** False during server render and first paint, so we never flash a signed-out UI. */
  ready: boolean;
  signIn: (token: string) => void;
  signOut: () => void;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const token = useSyncExternalStore(subscribe, readToken, serverToken);
  const ready = useSyncExternalStore(subscribe, clientReady, serverReady);

  const signIn = useCallback((next: string) => writeToken(next), []);
  const signOut = useCallback(() => writeToken(null), []);

  const value = useMemo<SessionValue>(
    () => ({ token, ready, signIn, signOut }),
    [token, ready, signIn, signOut],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (value === null) {
    throw new Error("useSession must be used inside <SessionProvider>");
  }
  return value;
}

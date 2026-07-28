"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { Profile } from "@fluentforge/contracts";

import {
  chooseTrack,
  fetchProfile,
  fetchTracks,
  type TrackOption,
  type TrackOptions,
} from "@/lib/api";
import { domainLabel } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { ErrorNotice, Loading } from "@/components/Status";

/**
 * What the learner is studying English for.
 *
 * Three tracks have been in `curriculum/tracks/` since the beginning, parsed
 * and validated and chosen by nobody, so a junior engineer who needs to
 * survive a standup and a postgraduate who needs to summarise three papers
 * were being offered the same plan.
 *
 * The screen shows each track's priority domains rather than only its name.
 * A track presented as a name with unstated consequences is the opaque
 * personalisation `docs/ADAPTIVE_ENGINE.md` refuses everywhere else — and the
 * learner is the only person who can tell us the choice is wrong for them.
 *
 * The caveats sit above the options, and the important one is that a track
 * never removes anything. Someone reading this needs to know they are not
 * trading away the basics for relevance.
 */
export default function TrackPage() {
  const router = useRouter();
  const { token, ready } = useSession();

  const [options, setOptions] = useState<TrackOptions | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    if (ready && token === null) router.replace("/sign-in");
  }, [ready, token, router]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    void (async () => {
      try {
        const [found, mine] = await Promise.all([
          fetchTracks(),
          fetchProfile(token),
        ]);
        if (!cancelled) {
          setOptions(found);
          setProfile(mine);
          setError(null);
        }
      } catch (cause) {
        if (!cancelled) setError(cause);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token]);

  if (!ready || (loading && !error)) {
    return (
      <main id="main" className="narrow">
        <Loading label="Loading what you can choose…" />
      </main>
    );
  }

  if (error) {
    return (
      <main id="main" className="narrow">
        <ErrorNotice error={error} onRetry={() => setError(null)} />
      </main>
    );
  }

  if (!token || !options || !profile) return null;

  async function pick(key: string) {
    if (!token) return;
    setSaving(key);
    try {
      setProfile(await chooseTrack(token, key));
      setError(null);
    } catch (cause) {
      setError(cause);
    } finally {
      setSaving(null);
    }
  }

  return (
    <main id="main" className="narrow">
      <p className="eyebrow">YOUR TRACK</p>
      <h1 className="page-title">What are you learning English for?</h1>

      {/* Above the options. Someone choosing needs to know they are not
          trading the basics away for relevance. */}
      <div className="notice" role="note">
        {options.caveats.map((caveat) => (
          <p key={caveat} className="hint">
            {caveat}
          </p>
        ))}
      </div>

      {/* The curriculum no longer defines what they picked. Saying so is
          better than showing a machine key as their chosen purpose. */}
      {profile.trackName === null ? (
        <p className="hint">
          The track you chose is no longer part of the curriculum. Your work is
          untouched &mdash; pick another below and planning carries on.
        </p>
      ) : null}

      <ul className="plan-list">
        {options.tracks.map((track) => (
          <li key={track.key}>
            <Track
              track={track}
              chosen={track.key === profile.trackKey}
              saving={saving === track.key}
              onPick={() => void pick(track.key)}
            />
          </li>
        ))}
      </ul>

      <p className="actions">
        <Link className="button" href="/dashboard">
          Back to today&rsquo;s plan
        </Link>
      </p>
    </main>
  );
}

function Track({
  track,
  chosen,
  saving,
  onPick,
}: {
  track: TrackOption;
  chosen: boolean;
  saving: boolean;
  onPick: () => void;
}) {
  return (
    <>
      <div className="plan-main">
        <strong>{track.name}</strong>
        {chosen ? <span className="plan-kind">Your track</span> : null}
      </div>

      {/* What choosing it actually does, in words rather than a name. */}
      <p className="plan-why">
        Puts more{" "}
        {track.priorityDomains.map((domain) => domainLabel(domain)).join(", ")}{" "}
        in your plan.
      </p>

      {track.scenarios.length > 0 ? (
        <p className="plan-why">
          For situations like{" "}
          {track.scenarios
            .slice(0, 3)
            .map((scenario) => scenario.replace(/_/g, " "))
            .join(", ")}
          .
        </p>
      ) : (
        <p className="plan-why">
          For no particular situation &mdash; a broad plan for using English day
          to day.
        </p>
      )}

      {chosen ? null : (
        <p className="actions">
          <button
            type="button"
            className="button-quiet"
            disabled={saving}
            onClick={onPick}
          >
            {saving ? "Switching…" : `Switch to ${track.name}`}
          </button>
        </p>
      )}
    </>
  );
}

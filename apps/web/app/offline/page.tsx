import Link from "next/link";

/**
 * What the service worker serves when a page was never cached and there is no
 * network.
 *
 * Its job is to be accurate rather than reassuring. A learner who thinks the
 * app is broken will close it; a learner who knows what offline costs them
 * here will come back.
 */
export const metadata = {
  title: "Offline · FluentForge",
};

export default function OfflinePage() {
  return (
    <main id="main" className="narrow">
      <p className="eyebrow">OFFLINE</p>
      <h1 className="page-title">This page needs a connection</h1>

      <div className="panel">
        <p>
          You have not opened this page before, so there is no saved copy to
          show you.
        </p>

        <h2 className="subheading">What still works</h2>
        <ul>
          <li>Today&rsquo;s plan, if you have loaded it today.</li>
          <li>Any activity you have already opened.</li>
          <li>Your profile as it stood the last time it loaded.</li>
        </ul>

        <h2 className="subheading">What does not</h2>
        <ul>
          <li>
            Checking anything you write or say. That happens on the server,
            against the curriculum and the model of what you know &mdash;
            neither of which lives in your browser.
          </li>
          <li>Reviews, which are scheduled server-side.</li>
        </ul>

        <p className="muted">
          Nothing you have written is lost while you are offline. It stays on
          screen until you send it.
        </p>

        <p className="actions">
          <Link className="button" href="/dashboard">
            Back to today&rsquo;s plan
          </Link>
        </p>
      </div>
    </main>
  );
}

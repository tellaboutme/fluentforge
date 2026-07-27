import Link from "next/link";

/**
 * Landing page.
 *
 * Deliberately claims nothing about the visitor's level. The previous version
 * of this page displayed invented CEFR estimates, which contradicted the rule
 * the API enforces.
 */
export default function HomePage() {
  return (
    <main id="main">
      <header className="hero">
        <p className="eyebrow">FLUENTFORGE</p>
        <h1>Build English you can use.</h1>
        <p className="lede">
          Your skills grow at different speeds, so FluentForge tracks them
          separately. Nothing is marked as learned until you have shown it in
          more than one situation.
        </p>
        <div className="actions">
          <Link className="button" href="/register">
            Start the diagnostic
          </Link>
          <Link className="button button-quiet" href="/sign-in">
            Sign in
          </Link>
        </div>
      </header>

      <section aria-labelledby="how-title" className="panel">
        <p className="eyebrow">HOW IT WORKS</p>
        <h2 id="how-title">Evidence, not points</h2>
        <ol className="steps">
          <li>
            <strong>A short diagnostic</strong>
            <span>
              Around 20 questions that adapt to your answers. It stops early
              rather than pushing you through items that are too hard.
            </span>
          </li>
          <li>
            <strong>A profile per skill</strong>
            <span>
              Grammar, vocabulary, reading, listening and the rest are tracked
              separately, each with its own confidence.
            </span>
          </li>
          <li>
            <strong>Honest estimates</strong>
            <span>
              A skill only gets a level once there is real evidence for it.
              Until then it says &ldquo;needs evidence&rdquo;.
            </span>
          </li>
        </ol>
      </section>
    </main>
  );
}

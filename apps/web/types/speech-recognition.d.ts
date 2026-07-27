/**
 * Web Speech API — the recognition half that TypeScript does not ship.
 *
 * TypeScript 5.9's DOM library has `SpeechRecognitionAlternative`,
 * `SpeechRecognitionResult` and `SpeechRecognitionResultList`, but stops
 * short of the interface that produces them: there is no `SpeechRecognition`,
 * no `SpeechRecognitionEvent`, and nothing on `Window`. The recognition
 * specification has never left draft, Chromium and Safari implement it
 * anyway (Safari and older Chromium only under the `webkit` prefix), and
 * Firefox does not implement it at all.
 *
 * So this declares exactly the missing surface that
 * `app/activity/[key]/page.tsx` touches, and reuses the lib's own types for
 * the parts it already defines. Declaring the whole draft would claim a
 * stability that does not exist; using `any` would be forbidden by
 * `CLAUDE.md` without a reason, and there is no reason here.
 *
 * Both constructors are optional on `window` deliberately. Absence is the
 * normal case, not an error case — the speaking lab notices it and offers
 * typing instead of crashing.
 */

interface SpeechRecognitionEvent extends Event {
  /** Where in `results` this event's new material starts. */
  readonly resultIndex: number;
  readonly results: SpeechRecognitionResultList;
}

interface SpeechRecognitionErrorEvent extends Event {
  readonly error: string;
  readonly message: string;
}

interface SpeechRecognition extends EventTarget {
  lang: string;
  /** Keep listening across pauses rather than stopping at the first one. */
  continuous: boolean;
  /** Emit provisional guesses, so words appear while the learner speaks. */
  interimResults: boolean;

  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;

  start(): void;
  /** Stop and deliver whatever has been recognised so far. */
  stop(): void;
  /** Stop and discard — used when the learner navigates away mid-answer. */
  abort(): void;
}

interface Window {
  SpeechRecognition?: new () => SpeechRecognition;
  webkitSpeechRecognition?: new () => SpeechRecognition;
}

# API Contracts

All endpoints are under `/api/v1`. Endpoints marked **implemented** exist today;
the rest are planned (see `docs/ROADMAP.md`).

## System (unversioned)

- `GET /health` — **implemented**. Liveness only; never touches the database.
- `GET /ready` — **implemented**. Reports database, active curriculum version,
  and provider modes. Returns `degraded` when no curriculum is loaded.

## Core endpoints

### Auth

- `POST /auth/register` — **implemented**. Creates an account and learner profile.
- `POST /auth/login` — **implemented**. Returns a bearer token.
- `GET /auth/me` — **implemented**.

Unknown email and wrong password return an identical response. Password policy
failures return `weak_password` and create no account.

### Curriculum

- `GET /curriculum` — **implemented**. The active version and its skill nodes.

### Profile

- `GET /profile` — **implemented**
- `PATCH /profile` — **implemented**
- `GET /profile/skill-map`
- `GET /profile/errors` — **implemented**. The learner's whole error log.

Each entry carries a rendered `label` (clients must never show the raw code),
the occurrence count, whether it blocks meaning, its priority, and whether it
has recurred often enough to be `scheduled` for practice — so a learner can
see that a single slip is recorded and not yet being drilled.

`remedy_key` points at a study unit that drills the feature, where one
exists. Where none does, `no_remedy_reason` says which kind of gap it is, and
the distinction is the point:

| value | meaning |
| --- | --- |
| `not_written` | no unit covers this feature yet |
| `no_feature` | a legacy `item.<skill>` code names a skill rather than a practisable feature, so nothing could honestly claim to fix it |
| `needs_speech` | a study unit is read and typed and cannot teach a sound contrast; this needs an audio pipeline the product does not have |

Collapsing those into a bare null would suggest a missing audio pipeline is a
backlog item. "We have not written this yet" and "nothing we can build in
this format would help" are different promises.

`GET /profile` returns a list of per-skill estimates. There is no field carrying
a single current level for the learner. `target_level` is a goal, not an
assessment. Each skill carries `mastery_probability`, `confidence`,
`evidence_count`, `distinct_contexts`, and a `status` of
`unobserved | emerging | supported | independent`. `cefr_estimate` is `null`
until the skill reaches `supported`; clients must render that as "needs
evidence", never as a low level.

### Diagnostic

- `POST /diagnostics` — **implemented**. Starts or resumes a session.
- `GET /diagnostics/{id}/next` — **implemented**
- `POST /diagnostics/{id}/responses` — **implemented**
- `POST /diagnostics/{id}/complete` — **implemented**
- `GET /diagnostics/{id}/report` — **implemented**

Item prompts never include an answer key; expected answers are returned only in
the response to a submission. `ability_estimate` is an internal routing number,
not a CEFR level and not a score to show the learner.

The report's `starting_band` says which level's content to open with. It is a
routing decision, not a placement: a short diagnostic cannot confirm a can-do
statement, so skills remain `emerging` until evidence accumulates across
contexts. `caveats` is always non-empty and must be surfaced in the UI.

### Plans and sessions

- `GET /plans/today` — **implemented**. Generates on first request, then stable
  for the rest of the day.
- `POST /plans/generate` — **implemented**. `{"regenerate": true}` replaces today's.
- `POST /sessions`
- `POST /sessions/{id}/complete`

Every plan item carries `reason_codes`, a learner-facing `explanation`, and the
full `components` breakdown that produced its priority — including components
that scored zero. `docs/ADAPTIVE_ENGINE.md` forbids an opaque score, so the
reasoning travels with the data rather than living only in the engine.
`unmet_constraints` lists anything the planner could not satisfy; a thin plan
must not look like a complete one.

### Activities and attempts

- `GET /activities/{activity_key}` — **implemented**. Opens an activity.
- `POST /activities/{activity_key}/complete` — **implemented**. Scores it and
  records evidence.
- `GET /attempts` — **implemented**. The learner's own past work, newest
  first, paginated by `before` rather than an offset.
- `GET /attempts/{id}/feedback` — **implemented**. One attempt in full.

Feedback is returned **as it was recorded**, never recomputed. The checks,
the curriculum version and the evaluator may all have moved since, and
re-deriving would show the learner a verdict nobody ever gave them. The
response carries `submitted_at`, the `evaluator_id` that produced it, and
`is_stale` — true whenever it might be judged differently today. Clients must
date the feedback rather than present it as current.

Reading history records nothing: no evidence, no new attempt, no re-scoring.
A system that recorded it would be counting rereading as practice.

Reflections appear in the list with `was_judged: false` and no score. Hiding
them would leave a gap in the learner's own record with no explanation;
showing a score would invent one.

Another learner's attempt returns exactly what a missing one returns. A
different status code would leak which attempts exist.

Both endpoints serve six activity kinds, discriminated on `activity_type`.
Clients must switch on that field; the shapes do not overlap.

| `activity_key` prefix | `activity_type` | Opened payload | Completed with |
| --- | --- | --- | --- |
| `read:` | `reading_task` | `body`, `word_count`, `questions[]` | `answers` |
| `study:` | `study_task` | `explanation`, `examples[]`, `items[]` | `answers`, `hints_used` |
| `write:` | `writing_task` | `prompt`, `guidance[]`, word and sentence requirements | `text` |
| `listen:` | `listening_task` | `setting`, `transcript`, `speech_rate`, `audio`, `questions[]` | `answers`, `plays`, `used_transcript` |
| `speak:` | `speaking_task` | `prompt`, `guidance[]`, `preparation_seconds`, `min_seconds`, `max_seconds`, `min_words` | `text`, `spoken_seconds`, `recognition_confidence`, `typed_instead` |
| `mediate:` | `mediation_task` | `brief`, `sources[]` (each with its full `text`), `guidance[]`, word requirements, `max_verbatim_words` | `text` |

Submitting the wrong payload for a kind returns `activity_payload_mismatch`
with the field it expected, rather than a generic validation failure.

An open activity never includes answers. For reading and study, `expected`
appears only in the completion response; a study unit's per-item `note` is
withheld until then too, because the note is the teaching moment and giving it
away first removes the retrieval.

What each kind evidences differs, and the difference is on the wire:

- **Reading** records `comprehension` — never production, however well the
  learner scores. Each text is its own evidence context.
- **Study** records `controlled_recall` at reduced `independence`, because the
  explanation stays on screen while the learner practises. The completion
  response returns that `independence` so a client can say why a perfect study
  score does not settle a skill. Revealed hints are self-reported in
  `hints_used` and lower it further. Each unit is one context, whatever its
  item count. Wrong items are logged as errors against the *linguistic
  feature* they exercised, returned in `logged_features`.
- **Listening** records `comprehension` against a *listening* skill, so
  understanding by ear and understanding by eye never merge into one number.
  Each clip is its own context. `plays` reduces `independence` past a small
  free allowance, because catching a clip in two passes is stronger evidence
  than needing six.

  The transcript **is** sent with the opened activity. It is the stimulus, not
  an answer key: the client speaks it, and a learner who cannot use audio has
  no other route through the exercise. What protects the measurement is
  disclosure rather than secrecy — a client that shows the transcript before
  the learner answers must send `used_transcript: true`, and the API then
  records **no listening evidence at all** and returns
  `evidence_recorded: false`. Clients must surface that: claiming someone
  understood speech when they read it is the same dishonesty as claiming
  unjudged writing was good.

  `audio` is `null` while a clip relies on browser speech synthesis. Synthetic
  speech under-represents the connected speech that makes listening hard, so
  the evidence records `synthesised: true` for later audit.

- **Writing** records `contextual_production` at reduced evaluator
  *confidence* (0.45): the learner demonstrably composed the text, but the
  countable checks did not judge its accuracy. A response too short to judge
  records no evidence at all rather than a bad score, and reports
  `evidence_recorded: false`.

  When a rubric evaluator is configured **and returns a usable judgement**, a
  *second* evidence event is added rather than the first being replaced — the
  two make different claims, and overwriting would lose the distinction. Both
  share one context key, so one piece of writing judged twice is one context.
  Evaluator confidence is capped at 0.85 before it reaches the mastery model:
  a model reporting near-certainty has not earned the trust of a closed item
  scored against a known answer.

  `provisional` is `true` until that happens, and clients must surface it —
  presenting a passed length check as good writing is forbidden by
  `docs/AI_TUTOR_BEHAVIOR.md`. When a rubric did run, the response carries
  `rubric[]` (each dimension with its score, confidence, and **quotations from
  the learner's own text**), at most three `priority_feedback[]` entries, and
  `evaluated_by`. A dimension with no cited evidence is a guess, so the
  citations travel with the score and clients should show them.

  An abstention, a confidence below 0.6, or a provider that fails all leave
  the learner with exactly the deterministic feedback they would have had.

- **Speaking** records `contextual_production` against a *speaking* skill, at
  the lowest evaluator confidence in the system (0.35). What the API receives
  is a transcript the browser produced, and a transcript is lossy in a way a
  typed answer is not: the recogniser may have misheard, dropped, or silently
  corrected what was said.

  Three rules follow, and clients must respect all three.

  **Nothing here evidences pronunciation.** A transcript is normalised text
  and cannot distinguish a clearly spoken word from a badly spoken one the
  recogniser guessed correctly. No task targets a `pronunciation.*` skill —
  the curriculum parser refuses one that tries — and evidence never lands on
  one. Every evidence event carries `pronunciation_unassessed: true` so a
  later reader cannot assume otherwise. `provisional` is always `true`, and
  clients must say plainly that delivery was not judged.

  **`recognition_confidence` is recorded and never scored.** Browser speech
  recognition is measurably worse on accented and non-native speech — this
  product's whole audience — so a low-confidence transcript may mean unclear
  speech, a poor microphone, or a recogniser trained mostly on native
  speakers. It is stored for audit and echoed back for display, and the same
  answer scores identically however well it was heard. Clients must present
  it as a fact about the software, not as a mark against the learner.

  **`typed_instead: true` records no speaking evidence at all**, the same
  shape as reading a listening transcript. The fallback exists so a learner
  with no microphone can still finish, the attempt is still kept, and the
  response says `evidence_recorded: false` with an explanation that does not
  imply cheating.

  `spoken_seconds` below the task's `min_seconds`, or a transcript below its
  word minimum, also records nothing rather than a bad score.

- **Mediation** records `contextual_production` against a *mediation* skill
  at the lowest deterministic confidence in the system (0.40, below writing's
  0.45). Everything the writing checks do still applies, and two checks are
  added that exist nowhere else.

  **Source coverage.** `used_sources` and `unused_sources` report which
  sources left a trace in the account. This is inferred from anchors — names,
  figures and dates that survive paraphrase — which the curriculum parser
  proves are present in their own source and absent from every other. It is
  an approximation, and clients must present it as one: a learner who
  covered a source without naming anything in it did nothing wrong.

  **Restating rather than transcribing.** `longest_copied_run` is the longest
  run of words the account shares with any source, after *marked quotations
  are removed* — quoting and attributing is legitimate mediation. It is
  returned whether or not it crossed the task's `max_verbatim_words`, so a
  learner can see how much headroom they had. `copied_from` names the source
  when the limit was crossed, and is `null` otherwise. The limit is sent with
  the opened activity so a client can state the rule before the learner
  writes rather than after they break it.

  The full text of every source **is** sent. It is the material, not an
  answer key. What is withheld is `anchors`: publishing the phrases coverage
  is checked against would turn a mediation task into a word hunt.

  `provisional` is always `true` until a rubric runs, and means something
  specific here. Nothing deterministic can tell whether the sources were
  conveyed *faithfully* — an anchor proves a figure was mentioned, not that
  it was reported correctly — and that is the whole point of the task.
  Clients must say so.

  A copied account still records evidence, at the lower score its failed
  check produces. Copying is a real thing the learner did with language and
  the deterministic pass caught it.

Plan items whose `activity_key` begins with `read:`, `study:`, `write:`,
`listen:`, `speak:`, or `mediate:` can be opened at these endpoints.
`review:` items belong to the review queue. `reflect:` has no activity yet
and must not be linked.

Error codes and features referenced by an activity are drawn from a closed
taxonomy (`apps/api/app/learning/taxonomy.py`). Codes are stable and never
renamed. Clients render `feature_label`, never the raw code.

### Benchmarks

- `GET /benchmarks/eligibility` — **implemented**. Whether one is due, and
  what has to happen if not.
- `POST /benchmarks` — **implemented**. Starts one, or refuses with
  `benchmark_not_due` (409) and the reason.
- `POST /benchmarks/{id}/responses` — **implemented**.
- `POST /benchmarks/{id}/complete` — **implemented**.

A benchmark is the only observation in the product that claims to *measure a
level* rather than record that something was practised, and it is the only
producer of `EvidenceType.BENCHMARK` — the joint-highest weight in the
mastery model. Four properties earn that weight, and each is visible on the
wire.

**It has no key, and the client does not choose it.** An activity is opened
by `activity_key`; a benchmark is asked for and either granted or refused.
A learner who could take one when they felt ready would be measuring their
confidence. `POST /benchmarks` returns the items the server picked.

**It is unaided, and `unaided: true` says so** on the opened session.
`POST /benchmarks/{id}/responses` **rejects unknown fields**, so there is no
`hints_used` to send — a benchmark taken with a hint is not a benchmark, and
a client sending one is told rather than having it dropped while the result
is recorded as unaided. Evidence is written at `independence: 1.0` and
evaluator confidence `1.0`, which is only defensible because the item types
are closed and the answers known in advance.

**Every item is one the learner has never met**, in any context. An item
already seen measures recall of that item. A benchmark that cannot be filled
from unseen material does not run, and the refusal says so.

**It can lower an estimate.** Everything else accumulates; this is the first
observation strong enough to move a profile down, and that is the point.
The completion response carries `lowered[]`, the skills whose estimate fell.
Clients must show it: a measurement that only ever agreed with the learner
would not be a measurement, and hiding a fall would quietly make it one.

The whole benchmark is **one evidence context per skill**, so eight items in
one sitting cannot satisfy the mastery model's breadth requirement on their
own.

Only closed item types are used. Written and spoken production stay
provisional until a rubric judges them, so including them would mean either
claiming certainty the checks cannot support or recording a benchmark that
is not one. Productive benchmarking waits for a judged deployment.

### Reflection

- `GET /reflection` — **implemented**. What the system has actually noticed.
- `POST /reflection` — **implemented**. Stores a note.

The only endpoint pair where a learner sends prose and **nothing judges it**.
That is stated on the wire — the response carries `scored: false` and
`evidence_recorded: false` — because a client has no other way to know, and a
screen implying otherwise would teach the learner to write reflections that
pass checks.

`GET` returns material rather than a question: at most three recurring errors
(each with a rendered `label`, never just the code, and `blocks_meaning` so
the client can order them), the skills nothing has observed lately, a count of
the learner's own work that stayed provisional, and their previous note. A
prompt built from nothing would have to invent something, so a learner with no
history gets empty lists and the client says so.

`unjudged_count` is the product admitting its own blind spot. Someone
reflecting on their progress should not read silence as approval.

`POST` has no minimum length. "Nothing new this week" is a legitimate
reflection and sometimes the true one; refusing it would make the learner
perform reflection rather than do it.

**No evidence is recorded, of any kind.** A learner who writes "I need to work
on the past simple" has not demonstrated the past simple, and counting the
sentence would record an intention as an achievement. The attempt is stored
because it is the learner's own history, and it touches no skill state.

Reflection has no `activity_key` and is not served by the activity endpoints:
its content is whatever the system noticed about this learner, so there is
nothing a client could name.

### Reviews

- `GET /reviews/due` — **implemented**. Capped; `due_now` reports the true total.
- `POST /reviews/seed` — **implemented**. Idempotent.
- `POST /reviews/{id}/answer` — **implemented**. Grade is one of
  `forgot | hard | good | easy`.

A due card returns `meaning` and `example` as `null`. They are populated only
in the answer response, after the learner has graded themselves — a card that
ships its own answer is not a retrieval test.

Each retrieval mode is a separate card with its own schedule. Answering one
records evidence of the type that mode can support: a recognition review is
never recorded as production.

### Content

- `POST /content/imports`
- `GET /content/imports/{id}`
- `GET /content/library`

### Speech uploads (not implemented)

Audio upload and acoustic analysis. This is the only route that could ever
evidence pronunciation, and until it exists no endpoint claims to.

- `POST /speech/uploads`
- `GET /speech/uploads/{id}/status`
- `GET /speech/uploads/{id}/feedback`

## Contract rules

- IDs are opaque strings or UUIDs.
- Timestamps are ISO-8601 UTC.
- Errors use `{code, message, details, request_id}` with stable machine codes.
  Current codes: `invalid_credentials`, `not_authenticated`, `account_inactive`,
  `email_already_registered`, `weak_password`, `profile_not_found`,
  `curriculum_not_loaded`, `session_not_found`, `diagnostic_complete`,
  `item_not_found`, `plan_not_found`, `review_not_found`, `activity_not_found`,
  `activity_payload_mismatch`, `validation_error`. Codes are never renamed or
  reused.
- Validation errors report field locations only; submitted content and
  credentials never appear in an error body or log.
- Every request and response carries an `X-Request-ID` header.
- Long-running requests return a job resource.
- Retryable writes accept `Idempotency-Key`.
- Every scored response exposes evaluator type and confidence.
- The API never reports an official CEFR certification.

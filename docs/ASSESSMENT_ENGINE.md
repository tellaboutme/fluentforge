# Assessment Engine

## Assessment types

- onboarding diagnostic;
- low-stakes formative checks;
- delayed retrieval checks;
- unit transfer tasks;
- monthly benchmark samples;
- learner-requested CEFR practice;
- portfolio evidence from authentic tasks.

## Evidence record

Every scored attempt should store:

- learner and skill node;
- task and curriculum version;
- item difficulty estimate;
- response and response modality;
- correctness or rubric dimensions;
- latency and duration;
- hints, retries, transcript edits, and scaffolds;
- evaluator type and version;
- evaluator confidence;
- timestamp and context;
- whether the task was seen before;
- evidence weight applied.

## Deterministic scoring

Use deterministic scoring for:

- exact or normalised retrieval;
- ordering;
- matching;
- selected-response comprehension;
- known-answer transformations;
- transcript-aligned listening blanks;
- pronunciation features when a reliable acoustic measure exists.

## Rubric scoring

Writing and speaking use analytic dimensions such as:

- task achievement;
- intelligibility/comprehensibility;
- range;
- grammatical control;
- vocabulary control and precision;
- fluency;
- coherence and cohesion;
- interaction;
- register/pragmatics;
- mediation quality.

Not every task uses every dimension.

## AI evaluator contract

AI evaluation must:

- return schema-valid JSON;
- quote or reference evidence from the learner response;
- distinguish error detection from suggested rewriting;
- provide confidence per dimension;
- abstain when audio/text quality is insufficient;
- avoid upgrading CEFR based on one response;
- be regression-tested against human-rated fixtures;
- never expose hidden reasoning to the learner.

## Mastery update

Initial implementation may use a transparent weighted Bayesian or Elo-like model. It must account for:

- task difficulty;
- evidence type;
- recency;
- hint level;
- first attempt vs immediate retry;
- repeated-item dependence;
- evaluator confidence;
- transfer to unseen contexts.

Keep raw evidence so the mastery model can be replaced later.

## Benchmark integrity

Benchmark tasks should:

- be isolated from teaching content where possible;
- rotate parallel forms;
- limit hints and retries;
- measure multiple skills;
- provide uncertainty rather than false precision;
- state that the result is an internal estimate, not an official certificate.

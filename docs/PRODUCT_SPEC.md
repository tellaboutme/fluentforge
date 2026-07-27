# Product Specification

## Product promise

FluentForge converts a learner's goals, current evidence, available time, interests, and recurring errors into a daily sequence of high-value language practice. It should help a learner move from assisted understanding to independent, precise use of English.

## Target user

Initial target: an adult learner around A1–A2 who uses English media and device interfaces but lacks structured active practice. The system must remain valid through C2.

## Core jobs

1. Tell me what I can actually do in English now.
2. Tell me the most valuable thing to practise next.
3. Make me retrieve and produce language, not merely recognize it.
4. Explain my mistakes in language I can understand.
5. Revisit material before I forget it.
6. Show credible progress across individual skills.
7. Prepare me for real conversations, work, study, media, and complex ideas.

## Capability domains

FluentForge tracks these top-level domains:

1. Listening comprehension
2. Spoken production
3. Spoken interaction
4. Pronunciation and phonological control
5. Reading comprehension
6. Written production
7. Written interaction
8. Vocabulary and phraseology
9. Grammar range and accuracy
10. Fluency and automaticity
11. Discourse, coherence, and cohesion
12. Pragmatics, register, and sociolinguistic appropriateness
13. Mediation: summarising, explaining, translating meaning, facilitating understanding
14. Learning strategies and self-correction

These domains are decomposed in `docs/SKILL_MATRIX.md`.

## Main product surfaces

### Onboarding and diagnostic

- goals, interests, native/explanation language, time budget;
- self-assessment against plain-language can-do statements;
- adaptive grammar/vocabulary recognition checks;
- short reading and listening tasks;
- writing sample;
- optional recorded speaking sample;
- initial skill profile with uncertainty ranges.

### Daily plan

A 20-, 40-, or 60-minute plan balancing:

- due retrieval reviews;
- the highest-priority weak prerequisite;
- one meaning-focused input activity;
- one output or interaction activity;
- pronunciation/fluency micro-practice;
- reflection or correction review.

### Skill labs

- Vocabulary Lab
- Grammar Lab
- Listening Lab
- Reading Lab
- Writing Lab
- Speaking Lab
- Pronunciation Lab
- Conversation Roleplays
- Mediation Lab
- Extensive Input Library

### Progress

- per-skill CEFR estimate and confidence;
- can-do evidence timeline;
- active vs receptive vocabulary;
- recurring error families;
- review load and retention estimate;
- monthly benchmark samples;
- “what improved / what remains weak / what to do next.”

## Motivation design

Use streaks only as a minor consistency aid. Primary rewards:

- mastered can-do outcomes;
- fewer repeated errors;
- longer unaided speech;
- better comprehension at higher speed;
- successful transfer to unseen content;
- completed authentic tasks.

No manipulative energy systems, artificial waiting, or mastery claims based on attendance.

## Product modes

- Guided Path: system chooses the plan.
- Goal Sprint: job interview, travel, technical meeting, exam, presentation.
- Free Practice: select any lab.
- Immersion: graded articles/audio/video with extraction and follow-up.
- Benchmark: periodic controlled assessment.

## Free/self-hostable principle

Core learning, local content, deterministic exercises, and progress tracking must work without a paid AI provider. AI features are optional accelerators. The provider layer must support disabled, local, and cloud modes.

## Success metrics

Learner outcome metrics:

- 30-day active retention;
- weekly minutes of meaningful production;
- decrease in repeated high-priority errors;
- transfer score on unseen tasks;
- growth in unaided speaking duration and words per minute without loss of intelligibility;
- CEFR can-do outcomes supported by multiple evidence types;
- learner-reported confidence calibrated against performance.

System quality metrics:

- evaluator agreement with human-rated fixtures;
- false mastery rate;
- content-level classification error;
- plan completion without overload;
- accessible task completion rate;
- response latency and generation failure rate.

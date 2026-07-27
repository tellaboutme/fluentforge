# Adaptive Planning Engine

## Inputs

- current mastery and confidence per skill node;
- prerequisite graph;
- due review items;
- recent errors;
- learner goals and interests;
- available minutes;
- fatigue and recent workload;
- modality availability: microphone, headphones, keyboard;
- content preferences and blocked topics;
- assessment uncertainty;
- planned benchmark schedule.

## Candidate priorities

For every eligible activity, calculate a priority from configurable components:

- urgency of scheduled review;
- expected learning gain;
- prerequisite importance;
- goal relevance;
- uncertainty reduction;
- skill balance;
- transfer value;
- learner interest;
- modality diversity;
- fatigue cost;
- recent repetition penalty.

Do not hard-code one opaque magic score. Log the component values so plan decisions are explainable.

## Daily plan constraints

A normal plan should:

- clear a manageable portion of due reviews;
- include at least one receptive and one productive activity;
- include speech regularly, not only when the learner selects it;
- avoid more than two cognitively heavy tasks consecutively;
- prevent a single skill from dominating the week unless a sprint goal demands it;
- include an authentic or meaning-focused task several times per week;
- reserve time for reviewing feedback.

## Session templates

### 20 minutes

- 5 min retrieval review
- 6 min target lesson
- 6 min output task
- 3 min correction/reflection

### 40 minutes

- 8 min retrieval review
- 10 min input/comprehension
- 8 min target form/phrase practice
- 10 min speaking or writing
- 4 min feedback/reflection

### 60 minutes

- 10 min retrieval review
- 15 min authentic input
- 10 min targeted language work
- 15 min speaking/writing/interaction
- 5 min pronunciation or fluency
- 5 min feedback and planning

## Review scheduler

Store memory state separately for:

- meaning recognition;
- form recognition;
- form recall;
- meaning recall;
- listening recognition;
- pronunciation production;
- contextual production.

A simple initial scheduler may use stability and difficulty parameters inspired by modern spaced-repetition systems, but it must remain independently testable and not claim perfect memory prediction.

## Explainability

The UI should be able to answer:

- Why is this in today's plan?
- Why did this item return?
- Why did my skill estimate change?
- What evidence is still missing?

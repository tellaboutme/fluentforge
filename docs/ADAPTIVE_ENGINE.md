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

## The skill graph

Edges are **authored, not derived**. They live in `curriculum/graph.yml`,
they are versioned and hashed with the rest of the curriculum, and every one
carries a written reason.

Until Milestone 6 they were derived: level N in a domain depended on level
N-1 in the same domain, every relation `prerequisite`, every weight 1.0. That
is one true claim repeated 45 times. It could not say that vocabulary gates
production, that interaction is listening and speaking happening at once, or
that pronunciation deliberately gates nothing at all.

Three kinds of claim can be written, and each expands to concrete edges:

| Block | Means |
| --- | --- |
| `ladders` | within one domain, each level depends on the one below it |
| `same_level` | a cross-domain claim holding at every level where both ends exist |
| `edges` | a specific claim about two named objectives |

Two relations are used. `prerequisite` is genuinely blocking: without it the
target is not merely harder, it is not attemptable. `supports` helps and does
not block — it is recorded because it is true, and the planner ignores it
when deciding what is holding a learner back. Inflating a supporting
relationship into a prerequisite is the main way a graph like this goes
wrong, so the distinction is enforced rather than advisory.

`weight` is **how strongly the claim is believed**, not how important the
skill is. 1.0 is definitional; 0.6 is "this is the consensus and the
exceptions are real". Weights multiply along a path, so a chain of tentative
claims counts for less than a chain of confident ones.

### What the graph must not be

`apps/api/app/curriculum/graph.py` refuses to load a graph that is any of
these, because every one of the failures is silent — the graph loads, the
planner believes it, and the learner gets a worse plan for reasons nobody
can see:

- **cyclic.** Every skill in a cycle needs every other one first, so none is
  ever startable.
- **backwards.** A prerequisite running from a higher CEFR level to a lower
  one would close no loop and quietly invert the plan.
- **orphaned.** An objective above the floor of its domain with nothing
  leading to it is content no plan can ever build towards.
- **unjustified.** An edge with no stated reason is a guess with a weight on
  it. The minimum is a sentence.
- **dead.** A rule matching no level is a claim the author believes is in
  force when it is not.
- **duplicated, self-referential, or weighted outside (0, 1].**

### Prerequisite importance

`_prerequisite_weakness` multiplies two things: how weak the learner is at a
skill, and how much that skill gates according to the graph.

The second factor used to be `1 - difficulty`, on the assumption that lower
level means blocks more. Within one domain that is nearly true; across
domains it is not, and the assumption was invisible in the plan explanation.
A2 vocabulary gates spoken and written production, and through them
interaction and mediation. A2 pronunciation gates almost nothing, by design.
The old proxy scored them identically.

`downstream_reach` in `apps/api/app/learning/skill_graph.py` walks the
prerequisite subgraph, takes the strongest path to each dependent, sums, and
normalises so the most load-bearing skill in the curriculum scores 1.0.
`make test-curriculum` prints the top five every run: a change in what the
planner pushes learners towards should be visible in a diff rather than
discovered in a plan.

A skill with no evidence still scores zero here. "We have never looked" is
not the same claim as "this is weak", and the uncertainty component already
covers the first.

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

# Curriculum

Curriculum files are source-controlled, versioned, and validated before publication.

## Stable IDs

Use lowercase dot-separated IDs such as:

- `grammar.tense.present_simple.habits`
- `speaking.interaction.clarification.basic`
- `reading.inference.author_attitude.b2`
- `mediation.summarise.multisource.c1`

IDs must never be reused for a different meaning.

## Files

| Path | Contents | Parser |
| --- | --- | --- |
| `framework.yml`, `levels/*.yml` | Objectives, one can-do per competency per level | `curriculum/parser.py` |
| `items/diagnostic.yml` | The diagnostic item bank | `curriculum/items.py` |
| `vocabulary/core-lexis.yml` | Phrase-first lexical entries and their review modes | `curriculum/lexis.py` |
| `content/library.yml` | Reading texts with comprehension questions | `curriculum/content.py` |
| `content/study.yml` | Focused study units: one point explained, then practice | `curriculum/study.py` |
| `content/writing.yml` | Written output tasks and their countable requirements | `curriculum/tasks.py` |
| `content/listening.yml` | Listening clips, transcripts, and playback pace | `curriculum/listening.py` |
| `content/speaking.yml` | Spoken output tasks, preparation and speaking times | `curriculum/speaking.py` |

Everything is validated together by `make test-curriculum`, which also reports
which linguistic features no study unit covers yet.

## Naming a feature

Every study practice item declares the linguistic **feature** it exercises, and
every writing task declares the features a rubric evaluator should judge. Codes
come from the closed taxonomy in `apps/api/app/learning/taxonomy.py`; an
unknown code is a validation failure, not a new category.

This is what makes a wrong answer actionable. `grammar.tense.perfect_vs_past`
can be practised; "something in `grammar.connected_time_modality` went wrong"
cannot.

## Authoring requirements

Every objective needs:

- level and domain;
- plain-language can-do outcome;
- prerequisites;
- examples;
- acceptable evidence types;
- minimum transfer requirements;
- common errors or confusions;
- content/topic constraints where relevant.

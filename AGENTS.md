# Agent Guide

## Domain map

| Area | Primary files | Specialist agent |
|---|---|---|
| Product behavior | `docs/PRODUCT_SPEC.md`, `docs/UX_FLOWS.md` | product-architect |
| Curriculum | `curriculum/**`, `docs/SKILL_MATRIX.md` | curriculum-designer |
| Adaptive planning | `docs/ADAPTIVE_ENGINE.md`, API domain code | learning-scientist |
| Assessment | `docs/ASSESSMENT_ENGINE.md`, evaluator prompts | assessment-engineer |
| Frontend | `apps/web/**` | frontend-engineer |
| Backend | `apps/api/**`, `services/worker/**` | backend-engineer |
| Quality | `tests/**`, CI | quality-engineer |

## Handoff format

Every substantial task should leave:

- files changed;
- learner behavior enabled;
- tests added or updated;
- commands run and results;
- unresolved risks;
- documentation updated.

## Parallel work safety

Agents may work in parallel only when their write scopes do not overlap. Shared contracts, migrations, curriculum schemas, and public API changes require one owner and an explicit integration step.

---
key: generation.lesson
version: 0.1.0
output_schema: packages/contracts/schemas/generated-activity.schema.json
---
Generate one activity that satisfies the provided curriculum objective, level, learner interests, allowed language, modality, and answer-key requirements.

The activity must:
- require the target skill rather than trivia;
- include clear instructions;
- avoid ambiguous answers unless rubric-scored;
- include deterministic answer criteria where possible;
- include likely misconceptions;
- include one transfer variant;
- avoid sensitive personal assumptions;
- return schema-valid JSON only.

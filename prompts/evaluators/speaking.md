---
key: evaluator.speaking
version: 0.1.0
output_schema: packages/contracts/schemas/speaking-evaluation.schema.json
---
Evaluate the transcript and supplied acoustic measurements against the task rubric.

Do not infer pronunciation quality solely from spelling in a transcript. Separate transcript-based language assessment from acoustic evidence. Return structured dimension scores, confidence, evidence, priority feedback, and abstentions.

# Privacy, Safety, and Trust

## Data minimisation

- Collect only learning-relevant profile data.
- Make microphone use optional except in explicitly selected speaking tasks.
- Allow text-only alternatives where possible.
- Default raw audio retention to a short configurable period.
- Provide export and deletion.
- Separate identifying data from research/aggregate analytics.

## AI transparency

- Label AI-generated lessons and provisional AI feedback.
- Show confidence or uncertainty where meaningful.
- Permit reporting bad feedback.
- Preserve model and prompt versions internally.
- Never claim an AI estimate is an official language certificate.

## Content safety

- Learners can block sensitive topics.
- Avoid unnecessarily graphic, sexual, hateful, or traumatic content in general practice.
- Advanced authentic content may discuss difficult subjects when intentionally selected and appropriately framed.
- Do not generate discriminatory accent judgments.

## Security baseline

- secrets server-side only;
- password hashing with a modern algorithm;
- CSRF/session protections according to auth design;
- rate limits on auth, generation, and uploads;
- file type and size validation;
- malware scanning for imported files when deployed publicly;
- signed object-storage access;
- audit logs for destructive actions.

# CLAUDE.md — SCADS agent entry point

You are implementing **SCADS**, a phone-first counterfeit-medicine risk screening and supply-chain intelligence platform.

This file is the entry point. It is intentionally short. Do not cram architecture into this file.

## Mandatory reading order

Before changing code, read:

1. `AGENTS.md` — operating contract for coding agents, failure recovery, validation, memory protocol.
2. `MEMORY.md` — living state of the project. Read first every session; update after every meaningful milestone.
3. `PLAN.md` — master dependency graph, phase gates, acceptance criteria, priorities.
4. `docs/PRODUCT_VISION.md` — product thesis, users, boundaries, MVP vs future.
5. `docs/ARCHITECTURE.md` — end-to-end technical architecture and request flows.
6. `docs/API_CONTRACTS.md` — API shapes and reason-code contract.
7. `docs/DATA_MODEL.md` — identifiers, DynamoDB schema, events, lifecycle.
8. `docs/SCORING_AND_DETECTION.md` — quality gate, physical matching, anomaly detection and fusion.
9. `docs/THREAT_MODEL.md` — attacker model and security requirements.
10. `docs/AWS_DEPLOYMENT.md` — AWS topology, IAM, deployment, observability and cost control.
11. `docs/SECURITY_PRIVACY.md` — privacy and data-handling constraints.
12. `docs/EVALUATION.md` — metrics, fixtures, ablations and evidence standards.
13. `docs/DEMO_AND_SUBMISSION.md` — exactly what must be visible in the submission.
14. `docs/ROADMAP.md` — future architecture; do not accidentally implement all of it during the hackathon.
15. `docs/RESEARCH_NOTES.md` — defensible external claims and source links.
16. The current phase file under `phases/`.
17. `MASTER_PROMPT.md` when operating as the primary end-to-end implementation agent.

## Product invariant

The core claim is not “AI recognizes fake medicine.”

The core claim is:

> SCADS combines independent evidence about **identity**, **physical packaging**, and **scan/supply-chain history**. A copied valid code, a good-looking package, or a clean database row alone is insufficient.

Internally preserve separate dimensions:

- `identity_score`
- `physical_score`
- `history_score`
- `product_status`
- `scan_quality`
- `decision`
- `reason_codes[]`

Never store only a single “trust score”.

## Safety-language invariant

Never call a pack “chemically genuine” or “safe to consume” from a phone scan.

Allowed result classes:

- `LOW_OBSERVED_RISK`
- `REVIEW_REQUIRED`
- `SUSPICIOUS`
- `UNABLE_TO_VERIFY`

Any uncertainty caused by blur, glare, crop, occlusion, unsupported packaging, missing reference, or OCR failure must be expressed as uncertainty, not counterfeit certainty.

## Implementation priority

When there is a conflict between ambitious architecture and a working submission:

1. protect the live vertical slice;
2. protect deterministic tests and reason codes;
3. protect AWS deployability;
4. protect the three demo scenarios;
5. defer roadmap sophistication.

## Source-of-truth hierarchy

1. `AGENTS.md`
2. `PLAN.md`
3. relevant `docs/*.md`
4. active `phases/*.md`
5. `MEMORY.md` for current implementation reality
6. comments / TODOs in code

If documentation conflicts with implementation reality, fix the documentation in the same change and log the decision in `MEMORY.md`.

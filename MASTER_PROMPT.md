# MASTER PROMPT — Hand this to Claude Code / Codex

You are the principal implementation agent for the repository **SCADS_AWS_FirstCommit**.

Your job is to implement the project end to end, not to brainstorm a new project.

## Operating mode

Work autonomously through the repository plan. Do not ask the user to re-explain phases that are already specified. If an implementation detail is underspecified, choose the simplest option consistent with the architecture, record the choice in `MEMORY.md`, and continue.

Before writing code, read in this exact order:

1. `CLAUDE.md`
2. `AGENTS.md`
3. `MEMORY.md`
4. `PLAN.md`
5. `docs/PRODUCT_VISION.md`
6. `docs/ARCHITECTURE.md`
7. `docs/API_CONTRACTS.md`
8. `docs/DATA_MODEL.md`
9. `docs/SCORING_AND_DETECTION.md`
10. `docs/THREAT_MODEL.md`
11. `docs/AWS_DEPLOYMENT.md`
12. `docs/SECURITY_PRIVACY.md`
13. `docs/EVALUATION.md`
14. `docs/DEMO_AND_SUBMISSION.md`
15. `docs/ROADMAP.md`
16. the active phase file in `phases/`

Then inspect the repository and update `MEMORY.md` with the actual starting state if it differs.

## Mission

Build a polished, working, AWS-deployed SCADS MVP for the First Commit hackathon.

The core product claim is:

> A QR/database lookup only says an identifier exists. SCADS checks whether the claimed identity, the physical package and the observed scan history agree.

The required demo must support:

1. **Clean seeded pack:** valid identity + good physical match + clean history.
2. **Visual tamper:** same valid identity but modified physical image; physical evidence drops.
3. **Cloned serial:** visually excellent pack and valid serial, but scan history contains an impossible/reused identity; result becomes suspicious.

The third scenario is mandatory unless a genuine technical blocker makes it impossible.

## Safety/product boundary

A phone image does not prove chemical contents.

Never output or market:
- “100% genuine”;
- “safe to consume”;
- “chemical authenticity verified”.

Use:
- `LOW_OBSERVED_RISK`
- `REVIEW_REQUIRED`
- `SUSPICIOUS`
- `UNABLE_TO_VERIFY`

Poor image quality must become `UNABLE_TO_VERIFY`, not “fake”.

## Architecture constraints

Default MVP:

```text
Amplify web
 -> API Gateway
 -> Lambda orchestrator
 -> S3 scans/references
 -> Textract for OCR
 -> deterministic CV worker
 -> DynamoDB registry + scan events
 -> deterministic decision engine
 -> frontend
```

Bedrock is optional and may:
- normalize ambiguous extracted fields;
- turn structured reason codes into clear prose.

Bedrock must **not** be the sole authenticity judge and a Bedrock outage must not break the core decision.

Prefer a Lambda container for OpenCV; if native dependency packaging becomes a repeated blocker, use App Runner rather than wasting the hackathon.

## Core engineering invariants

Maintain separate:
- identity score/status;
- physical score/status;
- history score/status;
- product status;
- scan quality;
- reason codes.

Do not store only a single trust score.

Implement the decision engine as a pure deterministic function with tests.

Use:
- quality gate;
- hard contradiction caps;
- weighted geometric/product-of-experts style fusion.

Do not use a naïve arithmetic average.

Every result stores:
- `pipeline_version`;
- `fusion_policy_version`;
- `reference_version`.

## Execution protocol

Work phase-by-phase in `PLAN.md`.

For each task:

1. Write/identify an acceptance test.
2. Implement the smallest change.
3. Run the narrow test.
4. Run regression checks.
5. If deployed behavior is involved, run the smoke test.
6. Update `MEMORY.md`.
7. Commit at meaningful phase gates.

Do not begin P1/P2 while P0 is unstable.

## Self-correction protocol

When a command, test or deploy fails:

1. Capture exact error.
2. Classify:
   - code defect;
   - contract mismatch;
   - environment/config;
   - dependency/API mismatch;
   - data/fixture;
   - architecture mismatch;
   - external/transient;
   - flaky.
3. Reduce to minimal reproduction.
4. Verify the assumption in code/docs/SDK.
5. Fix the root cause.
6. Rerun narrow test.
7. Rerun regression.
8. Update relevant docs if design changed.
9. Update `MEMORY.md` with failure + solution.

Never “fix” by:
- deleting a test;
- silently catching errors;
- widening thresholds without evidence;
- returning success when a dependency failed;
- changing demo fixtures until an incorrect algorithm passes;
- replacing required AWS behavior with local-only mocks;
- allowing LLM prose to change the decision.

If you fail three times on the same infrastructure mechanism, stop repeating the same approach. Choose the documented fallback and record the decision.

## Memory protocol

`MEMORY.md` is your persistent handoff.

After every meaningful milestone append/update:
- current phase;
- completed features;
- commands that work;
- deployed URLs/resource names that are safe to record;
- tests and results;
- architecture deviations;
- unresolved risks;
- exact next task.

Keep secrets out.

If you discover that a source-of-truth document is wrong, update that document and `MEMORY.md` in the same change.

## Implementation preference

Favor:
- readable code;
- explicit contracts;
- tests;
- deterministic behavior;
- a small number of AWS services;
- robust error states.

Avoid:
- premature microservices;
- blockchain;
- GNNs;
- large ML training;
- graph databases;
- full regulatory integrations;
until the P0 submission is complete.

## UI

Make it mobile-first and visually strong.

The result screen must show three evidence dimensions separately.

Example:

```text
Identity        VALID
Physical pack   MATCH
Scan history    CONTRADICTION

Reason:
This serial was recorded in a distant demo location too recently to be plausible.

Decision:
SUSPICIOUS
```

Always include the limitation that packaging checks do not assay chemical contents.

If time allows, implement:
- tamper slider;
- mismatch overlay;
- scan history timeline.

But never at the expense of the three core scenarios.

## Research/evaluation honesty

Synthetic tampering is a controlled proxy, not a real counterfeit benchmark.

Do not invent accuracy.

If you produce metrics, label dataset size and fixture source.

Read `docs/RESEARCH_NOTES.md` before writing README claims.

## AWS / cost

Ship It rewards actual AWS deployment and architecture/cost thinking.

Keep:
- private S3;
- direct uploads;
- serverless;
- DynamoDB on-demand;
- short retention;
- no always-on GPU;
- optional Bedrock;
- least-privilege IAM.

Build a repeatable deployment path.

## Final phase behavior

Before submission:
- secret scan;
- all tests;
- smoke test;
- reset demo;
- five full scenario rehearsals;
- public URL incognito check;
- README;
- architecture diagram;
- <=3-minute video plan;
- stable tag/commit.

Do not make risky refactors after the stable recording unless a submission-blocking bug exists.

## Your first action

Read all mandatory files, inspect git status/repo layout, run any existing tests, then update `MEMORY.md` with the actual state.

Then execute `phases/PHASE_0_FOUNDATION.md`.

Continue through P0 phases without asking the user to repeat planning.

# AGENTS.md — Operating contract for Claude Code, Codex and other coding agents

## 1. Mission

Build SCADS end to end as a **working AWS-deployed product**, while preserving a clean path from the hackathon MVP to a serious anti-counterfeit platform.

You are not being asked to brainstorm each phase again. The planning is already encoded in this repository. Execute it, validate it, and improve it only when evidence shows a change is necessary.

## 2. Documents and what each one is for

Do not put all context into this file.

| File | Purpose |
|---|---|
| `CLAUDE.md` | concise entry point and read order |
| `MEMORY.md` | living implementation state and learned facts |
| `PLAN.md` | master phase plan, priority and acceptance gates |
| `docs/PRODUCT_VISION.md` | users, problem, product thesis, scope boundaries |
| `docs/ARCHITECTURE.md` | system boundaries and request flows |
| `docs/API_CONTRACTS.md` | endpoint and payload contract |
| `docs/DATA_MODEL.md` | DynamoDB/entity/event schema and access patterns |
| `docs/SCORING_AND_DETECTION.md` | actual detection logic and fusion policy |
| `docs/THREAT_MODEL.md` | attackers, abuse paths and mitigations |
| `docs/AWS_DEPLOYMENT.md` | cloud/IaC/deployment/observability |
| `docs/SECURITY_PRIVACY.md` | identity, privacy, data retention and secure defaults |
| `docs/EVALUATION.md` | how correctness is measured |
| `docs/DEMO_AND_SUBMISSION.md` | judge-facing demonstration and submission requirements |
| `docs/ROADMAP.md` | long-term layers that must not derail MVP |
| `docs/RESEARCH_NOTES.md` | defensible research/regulatory context |
| `phases/*.md` | executable phase-by-phase work packages |
| `MASTER_PROMPT.md` | top-level autonomous implementation instructions |

## 3. Session bootstrap

At the beginning of every coding session:

1. Read `MEMORY.md`.
2. Inspect `git status`, current branch and recent commits.
3. Determine the active phase from `MEMORY.md` and `PLAN.md`.
4. Read only the architecture files relevant to that phase, plus this file.
5. Run the fastest existing health checks before editing:
   - unit tests
   - type check
   - lint
   - build
   - relevant smoke test
6. Record any pre-existing failure in `MEMORY.md`; do not silently attribute it to your new code.

## 4. Work-unit protocol

For each work unit:

### 4.1 State the acceptance test first

Examples:

- “Given a seeded serial and a valid reference image, `/scans` returns `LOW_OBSERVED_RISK` with `IDENTITY_VALID` and `PHYSICAL_MATCH`.”
- “Given the same serial scanned 800 km apart within 60 minutes, result includes `IMPOSSIBLE_TRAVEL` and is capped at `SUSPICIOUS`.”
- “Given a blurred image below the quality threshold, the system returns `UNABLE_TO_VERIFY`, not `SUSPICIOUS`.”

### 4.2 Implement the smallest vertical change

Avoid speculative frameworks. Prefer a boring function with tests over a generic abstraction with no current caller.

### 4.3 Validate immediately

Run the narrow test, then the broader suite.

### 4.4 Update memory

Every meaningful completed unit updates `MEMORY.md` with:

- what changed;
- why;
- tests run and results;
- new commands/environment requirements;
- discovered constraints;
- deviations from docs;
- unresolved risks;
- next exact task.

## 5. Self-correction loop

When something fails, do not thrash.

Classify the failure into exactly one primary category:

1. **Code defect** — logic/type/runtime bug in our code.
2. **Contract mismatch** — frontend/backend/schema/reason-code disagreement.
3. **Environment/configuration** — env vars, permissions, region, credential, build image, runtime.
4. **Dependency/API mismatch** — SDK version, AWS API behavior, package incompatibility.
5. **Data/fixture issue** — missing seeded record, malformed image, invalid reference, clock/location fixture.
6. **Architecture mismatch** — implementation exposes a flaw in the current design.
7. **External/transient** — service outage, throttling, network failure.
8. **Flaky test** — nondeterminism or timing.

Then:

- capture the exact error;
- reduce to the smallest reproduction;
- inspect the relevant documentation and contract;
- verify assumptions against actual SDK/API behavior;
- change one root cause at a time;
- rerun the smallest test;
- rerun the regression suite;
- update docs if the architecture/contract changed;
- update `MEMORY.md`.

### Forbidden “fixes”

Do not:

- delete or skip a failing test merely to obtain green CI;
- widen thresholds until a bad fixture passes without evidence;
- catch `Exception` and return a success-like fallback;
- replace production code with mocks to hide a deployment problem;
- use a Bedrock model output as ground truth for the authenticity verdict;
- hardcode AWS credentials;
- silently downgrade a required AWS integration to local-only behavior;
- mutate historical scan events to make an anomaly disappear.

## 6. Engineering rules

### 6.1 Core verdict must be reproducible

The decision engine must be a pure/testable function over structured signal inputs.

Foundation-model output may help extract/normalize metadata or explain the verdict, but cannot be the sole determinant of authenticity.

### 6.2 Quality failure is not counterfeit evidence

A poor scan returns `UNABLE_TO_VERIFY`.

Never punish bad lighting as if it proves counterfeiting.

### 6.3 Separate state from evidence

- A batch may be expired while the package is authentic.
- A serial may be valid while its current scan is suspicious because it was cloned.
- A package may visually match while supply-chain history contradicts it.

Keep these separate.

### 6.4 Prefer reason codes to prose

Backend first returns stable codes. Frontend maps codes to user explanations.

### 6.5 Preserve raw evidence references

Store S3 object keys, extraction output, scalar features, algorithm version and threshold version for debugging. Do not store unbounded sensitive metadata.

### 6.6 Version models and policies

Every result should record:

- `pipeline_version`
- `fusion_policy_version`
- `reference_version`
- optional `model_version`

This allows later re-evaluation.

## 7. Repository structure target

Suggested shape:

```text
/
  apps/
    web/
    api/
  packages/
    contracts/
    detection/
    decision-engine/
    shared/
  infra/
    template.yaml
  scripts/
    seed_demo.py
    generate_tamper_fixtures.py
    smoke_test.py
  tests/
    fixtures/
  docs/
  phases/
  CLAUDE.md
  AGENTS.md
  MEMORY.md
  PLAN.md
  MASTER_PROMPT.md
```

Do not force a monorepo tool if the codebase remains small. A simple workspace is fine.

## 8. Branch / commit discipline

During hackathon execution:

- commit at each phase gate;
- use descriptive commits (`feat: add serial-history anomaly gate`);
- keep the public history honest and within event constraints;
- never squash away the entire build story right before submission;
- do not commit `.env`, credentials or private data.

## 9. AWS discipline

Before adding a service ask:

1. Does it improve the actual product or judging evidence?
2. Can it be configured and demonstrated reliably before deadline?
3. Is there a simpler AWS primitive already in the stack?

The core MVP should remain understandable:

`Amplify -> API Gateway -> Lambda -> S3/Textract/DynamoDB -> decision engine -> response`

Bedrock is optional but useful for structured normalization/explanation if it does not threaten reliability.

## 10. Cost discipline

- set explicit AWS region in IaC/config;
- S3 lifecycle demo uploads;
- DynamoDB on-demand for hackathon;
- CloudWatch retention short in dev;
- avoid always-on GPU/EC2;
- prefer Lambda/App Runner only when needed;
- add budget alarm if account supports it;
- never place expensive Bedrock inference in a polling loop.

## 11. Security discipline

- presigned S3 uploads with content type/size constraints;
- randomized object keys;
- no public S3 buckets;
- API rate limiting where feasible;
- validate file signatures, not only file extensions;
- strip or ignore unneeded EXIF;
- store coarse location only if the user explicitly grants it;
- admin/demo mutation endpoints must not be public;
- manufacturer enrollment is authenticated, not consumer-writable;
- result records are append-only from the consumer perspective.

See `docs/THREAT_MODEL.md` and `docs/SECURITY_PRIVACY.md`.

## 12. Definition of done

A feature is done only when:

- code exists;
- automated test exists where practical;
- error path exists;
- logs are useful;
- contract is documented;
- the deployed path works if the feature is part of the demo;
- `MEMORY.md` is updated.

## 13. Stop conditions

If the deployed vertical slice is broken, stop adding features.

If less than one major work block remains before submission, execute only `P0` items in `PLAN.md`.

If uncertain whether to add a roadmap feature, do not. Put it in `MEMORY.md` or `docs/ROADMAP.md` and protect the demo.

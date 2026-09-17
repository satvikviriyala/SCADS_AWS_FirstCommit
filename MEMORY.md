# MEMORY.md — Living project memory

> Coding agents: read this file at the start of every session and update it after every meaningful task. Keep it concise enough to scan, but complete enough that a fresh agent can resume without asking Satvik to repeat decisions.

## Project

- Name: SCADS
- Repository: `satvikviriyala/SCADS_AWS_FirstCommit`
- Event: WeMakeDevs × AWS Builder Center, First Commit, Sept 17–20 2026.
- Target: Ship It track; public AWS URL; <=3 minute demo.
- Core thesis: verify **identity + physical package evidence + event/history context**, rather than merely checking whether a QR/batch exists.
- Safety boundary: phone screening cannot prove chemical composition or medicine safety.

## Current phase

`PHASE_0_FOUNDATION`

## Current implementation status

- Repository initially contained only a minimal `README.md`.
- Planning package was generated before implementation.
- No code implementation should be assumed until this section is updated by the coding agent.

## Locked architecture decisions

1. Frontend should be mobile-first and hosted on Amplify.
2. Upload image to private S3 using a presigned URL.
3. API Gateway + Lambda is the default request path.
4. Textract is the deterministic OCR/text-box source for the MVP; direct QR decoding should happen client-side or in the backend when possible.
5. Bedrock is optional for ambiguous metadata normalization and user-facing explanation, not the sole authenticity judge.
6. Physical comparison first runs a scan-quality gate, then registration, then per-feature comparisons.
7. Decision engine stores separate identity, physical, history and product-status dimensions.
8. Fusion uses contradiction gates plus a weighted geometric / product-of-experts style aggregation. Do not use a naïve arithmetic average.
9. Add one visible history anomaly to the MVP: duplicate/impossible-travel serial simulation.
10. Result classes: `LOW_OBSERVED_RISK`, `REVIEW_REQUIRED`, `SUSPICIOUS`, `UNABLE_TO_VERIFY`.
11. Every result includes stable reason codes.
12. Design identifiers as `serial -> batch -> SKU -> manufacturer`, while retaining batch fallback for demo products without serials.
13. Raw scan events are append-only logically; corrections create new events/findings rather than rewriting history.
14. The architecture should be EPCIS-friendly long term without requiring EPCIS implementation for the hackathon.

## Tentative choices that agents may change with evidence

- React/Vite vs Next.js frontend.
- SAM vs CDK.
- Lambda container vs App Runner for OpenCV.
- Exact Textract API.
- Exact numeric thresholds in demo scoring.
- Whether location is entered through a demo scenario selector instead of browser geolocation.
- Bedrock model selection.

Any change to a locked decision requires:
1. evidence;
2. update to relevant docs;
3. entry in Decision Log below.

## Demo scenarios

### Scenario A — clean reference
Expected: `LOW_OBSERVED_RISK`.
Evidence: identity valid, physical match good, no contradictory prior scans.

### Scenario B — visually tampered but valid identifier
Use a known real reference and a synthetically perturbed image.
Expected: `SUSPICIOUS` or `REVIEW_REQUIRED` depending on perturbation.
Reason examples: `TEXT_LAYOUT_MISMATCH`, `STRUCTURAL_MISMATCH`, `PRINT_SHARPNESS_MISMATCH`.

### Scenario C — perfect-looking cloned identity
Same visual/reference can match strongly, but serial was already scanned or sold far away recently.
Expected: `SUSPICIOUS`.
Reason examples: `SERIAL_REUSE`, `IMPOSSIBLE_TRAVEL`, `POST_SALE_REUSE`.
This scenario is strategically important because it demonstrates why SCADS is not a QR scanner.

## Decision log

| Date | Decision | Why | Evidence / impact |
|---|---|---|---|
| 2026-09-18 | Use WHO “1 in 10 in LMICs” framing rather than “1 million deaths/year” | More defensible primary-source claim | See `docs/RESEARCH_NOTES.md` |
| 2026-09-18 | Core verdict deterministic; Bedrock optional/explanatory | Repeatability, auditability, easier judging | Architecture/scoring docs |
| 2026-09-18 | Add scan-history anomaly to hackathon MVP | Distinguishes SCADS from database lookup systems | Demo scenario C |
| 2026-09-18 | Poor scan => unverifiable, not counterfeit | Prevent false accusation caused by camera conditions | Detection policy |

## Known risks

- Generic “visual comparison against one stock reference” can confuse manufacturing variation, lighting and camera artifacts with counterfeiting. Registration + quality gating + ROI-based reference profiles are required.
- Synthetic perturbations are evaluation/demo proxies, not proof of real counterfeit accuracy.
- No chemical-content claim is supportable from packaging images.
- Location-based anomaly detection must avoid invasive collection; use coarse or synthetic locations in the hackathon.
- OCR latency can affect synchronous UX.
- OpenCV/scikit-image Lambda package size may push toward a container image.
- A single serial reused many times can be legitimate during testing; environment/demo fixtures need namespaces or reset scripts.

## Environment checklist

Update as implementation lands:

- AWS region: TBD
- Amplify URL: TBD
- API base URL: TBD
- S3 upload bucket: TBD
- DynamoDB tables: TBD
- Textract enabled: TBD
- Bedrock model/region: TBD
- Deployment command: TBD
- Smoke-test command: TBD
- Demo seed command: TBD

## Last verified test state

Not yet implemented.

## Next exact task

Execute `phases/PHASE_0_FOUNDATION.md`, then `PHASE_1_VERTICAL_SLICE.md`.

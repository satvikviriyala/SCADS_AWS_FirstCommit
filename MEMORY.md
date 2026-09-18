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

`PHASE_3_PHYSICAL` complete. Next: `PHASE_1_VERTICAL_SLICE` (API + web + AWS), then `PHASE_4`
fusion wiring into the orchestrator.

Note the phase order deviation: P0-P2-P3 (pure detection core) were built before P1
(deployment), because this workstation has no AWS CLI, no SAM CLI and no Docker
(see "Environment reality" below). Building the testable core first was the only
way to make progress; the deployment path is written to be runnable the moment
credentials exist.

## Current implementation status

Implemented and tested (234 tests, all passing, `.venv/bin/python -m pytest tests/ -q`):

- `packages/scads/scads/contracts/` — four-class decision enum, 34-code reason registry
  with severity/category metadata, evidence models, DynamoDB record shapes.
- `packages/scads/scads/decision/` — versioned `FusionPolicy` + pure `decide()`;
  weighted geometric fusion, hard score caps, decision-class ceilings; deterministic
  explanation layer.
- `packages/scads/scads/identity/` — QR parsing (SCADS demo / GS1 bracketed and FNC1 /
  JSON / labelled URL), expiry normalisation, registry evaluation keeping *claimed*
  and *resolved* identity separate.
- `packages/scads/scads/history/` — impossible travel, serial reuse, post-sale reuse,
  scan-velocity burst, over named coarse locations.
- `packages/scads/scads/physical/` — upload validation, quality gate, quad-detection +
  DLT homography registration, SSIM/layout/content/print features. numpy + Pillow only.
- `packages/scads/scads/adapters/` — S3/DynamoDB/Textract/Bedrock and offline
  filesystem/JSON backends behind one set of ports.
- `packages/scads/scads/demo/` — shared seed data, pack renderer, capture simulator,
  21-fixture corpus, measurement-based reference enrollment.
- `scripts/calibrate.py` — the measurement harness behind every threshold.

Not yet implemented: the API handlers/orchestrator, the web frontend, the SAM template,
the deploy/seed/smoke scripts.

## Environment reality (important for any agent resuming this work)

This workstation has **no node/npm, no AWS CLI, no SAM CLI, no Docker, and no AWS
credentials**. Python is the system 3.9.6. `pip install` works (network is available).

Consequences, all deliberate:

1. **No OpenCV.** `opencv-python-headless` + numpy unzips to 223 MB — within 27 MB of
   the Lambda 250 MB limit, carrying two copies of OpenBLAS and the whole ffmpeg stack
   for code that only needed `imdecode`, ORB and `warpPerspective`. numpy + Pillow is
   79 MB. Since Docker is unavailable, the documented "Lambda container image" fallback
   could not be built or tested here either. So the detection pipeline is numpy + Pillow
   only, and registration uses quadrilateral detection + a four-point DLT homography
   instead of ORB — which suits a planar carton better anyway.
2. **QR decode moves to the client.** `cv2.QRCodeDetector` is gone with OpenCV. The
   browser's `BarcodeDetector` decodes and posts `qr_payload` (already in the API
   contract), with Textract OCR of the printed serial as the documented fallback.
3. **Frontend is a zero-build static PWA** (vanilla ES modules). No npm to build a
   React/Vite bundle. Amplify Hosting serves it as static assets with no build step.
4. **Deployment uses boto3 + CloudFormation directly**, not `sam deploy`.
   CloudFormation applies the `AWS::Serverless-2016-10-31` transform server-side, so a
   SAM template deploys fine via `create_change_set` with `CAPABILITY_AUTO_EXPAND`.
5. **Code is Python 3.9-compatible** (no `match`, no PEP 604 unions at runtime) so tests
   run locally, while Lambda runs 3.12.

## Measured detection performance

From `.venv/bin/python scripts/calibrate.py` over the 21-fixture corpus. Synthetic
tampering is a controlled proxy, **not** a counterfeit benchmark — see
`docs/EVALUATION.md` section 1. Do not restate these as counterfeit accuracy.

| Measurement | Result |
|---|---|
| artwork tampers flagged by a physical reason code | 5 / 5 |
| genuine packs false-flagged | 0 / 8 |
| identity tampers correctly leaving packaging clean | 3 / 3 |
| difficult captures gated before comparison | 4 / 5 (the 5th fails registration) |
| genuine physical score (min / median) | 0.846 / 0.874 |
| artwork-tamper physical score (median / max) | 0.825 / 0.839 |
| separation margin on the aggregate score | 0.007 |
| pipeline latency (median / max) | 451 ms / 524 ms |

The 0.007 margin is the honest headline: **the aggregate physical score barely
separates genuine from tampered, and the per-feature reason codes are what actually
carry the signal.** That is why the architecture emits codes rather than a scalar, and
why the fusion policy acts on codes through caps and ceilings.

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

`234 passed` via `.venv/bin/python -m pytest tests/ -q`. No known failures.

## Commands that work

```bash
# one-time local setup (already done in this checkout)
python3 -m venv .venv
.venv/bin/pip install "numpy<2.1" pillow boto3 pytest segno

.venv/bin/python -m pytest tests/ -q              # full suite
.venv/bin/python -m pytest tests/unit -q -m "not slow"   # fast subset
.venv/bin/python scripts/calibrate.py             # threshold evidence table
.venv/bin/python scripts/calibrate.py --sweep logo_shift
```

## Next exact task

Build the API layer: `scads/api/` (router, request validation, orchestrator wiring
quality -> identity -> physical -> history -> fusion), `apps/api/handler.py` as the
Lambda entry point, then `scripts/dev_server.py` so the whole path runs locally on the
offline backends. After that the SAM template and `scripts/deploy.py`.

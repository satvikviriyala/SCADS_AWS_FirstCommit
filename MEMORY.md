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

**P0 complete except the two steps that require AWS credentials.** Phases 0, 2, 3, 4,
5 and 6 are done; Phase 1 (deployed slice) and Phase 7 (submission) are blocked only on
credentials and a recording.

Phase order deviation, deliberate: the detection core (P0/P2/P3/P4) was built before
deployment (P1) because this workstation has no AWS CLI, no SAM CLI, no Docker and no
credentials. Building the testable core first was the only way to make progress. The
deployment path is complete and runnable the moment credentials exist:

```bash
python scripts/deploy.py --region ap-south-1          # stack + seed + smoke
python scripts/deploy_web.py --api-url https://...    # Amplify
```

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

- `packages/scads/scads/api/` — routing, validation, the scan orchestrator.
- `apps/web/` — zero-build mobile PWA; `apps/api/handler.py` — Lambda entry.
- `infra/template.yaml` — SAM template.
- `scripts/` — `seed_demo`, `calibrate`, `dev_server`, `package_lambda`, `deploy`,
  `deploy_web`, `smoke_test`, `secret_scan`.

**Not done:** the actual AWS deployment (no credentials), the demo recording, and the
submission. WAF and a latency dashboard remain P1.

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

## Previously tentative choices, now settled

| Question | Settled as | Why |
|---|---|---|
| React/Vite vs Next.js | Neither — plain HTML/CSS/ES modules | No Node toolchain here; Amplify serves static assets with no build |
| SAM vs CDK | SAM template, deployed via boto3 | CloudFormation applies the transform server-side; no CLI needed |
| Lambda container vs App Runner for OpenCV | Neither — OpenCV removed | 223 MB vs 79 MB; Docker unavailable. See ARCHITECTURE section 5 |
| Exact Textract API | `detect_document_text` | Needs word geometry, not forms; cheaper and lower latency |
| Numeric thresholds | Set from `scripts/calibrate.py` | Measured over the fixture corpus, not chosen by feel |
| Location input | Named simulated locations in a selector | Never requests real location; every surface labels it simulated |
| Bedrock model | Claude 3.5 Haiku, disabled by default | Explanation only; cheapest adequate model; never authoritative |

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
| 2026-09-18 | Drop OpenCV; numpy + Pillow only | 223 MB vs 79 MB unzipped against a 250 MB Lambda limit; Docker unavailable for the documented container fallback | `docs/ARCHITECTURE.md` section 5; `scripts/package_lambda.py` |
| 2026-09-18 | Registration by quad detection + four-point DLT homography, not ORB | A carton is a planar rectangle; stronger prior than generic keypoints, deterministic, numpy-only | `packages/scads/scads/physical/registration.py` |
| 2026-09-18 | Zero-build static frontend | No Node toolchain; removes the entire bundler failure mode from the demo path | `apps/web/` |
| 2026-09-18 | Deploy via boto3 + CloudFormation change sets | No AWS CLI or SAM CLI available; CloudFormation runs the SAM transform server-side | `scripts/deploy.py` |
| 2026-09-18 | General contradiction ceiling added to the fusion policy | Geometric fusion alone still cleared 0.75 with one dimension failing and two near-perfect | `tests/unit/test_fusion.py` |
| 2026-09-18 | Severe-physical cap and region-consistency finding conditioned on registration confidence | Both fired on a genuine pack photographed off-axis; camera geometry must not manufacture accusations | `packages/scads/scads/physical/pipeline.py` |
| 2026-09-18 | `print_sharpness` refuses to report on a soft capture | Defocus and poor printing are confounded in one image; a genuine pack scored 0.28 and was reported as a print mismatch | `packages/scads/scads/physical/features.py` |
| 2026-09-18 | Reference anchors measured from rendered artwork, not hand-written | Guessed coordinates held `text_layout` at 0.69 for every fixture; the guess error exceeded the signal | `packages/scads/scads/demo/enroll.py` |
| 2026-09-18 | Demo traffic self-tags so the reset can clear it | Five-run rehearsal drifted: accumulated scans correctly produced SERIAL_REUSE against the clean pack | `tests/integration/test_scan_flow.py` |

## Known risks

- Generic “visual comparison against one stock reference” can confuse manufacturing variation, lighting and camera artifacts with counterfeiting. Registration + quality gating + ROI-based reference profiles are required.
- Synthetic perturbations are evaluation/demo proxies, not proof of real counterfeit accuracy.
- No chemical-content claim is supportable from packaging images.
- Location-based anomaly detection must avoid invasive collection; use coarse or synthetic locations in the hackathon.
- OCR latency can affect synchronous UX.
- OpenCV/scikit-image Lambda package size may push toward a container image.
- A single serial reused many times can be legitimate during testing. **Resolved:** demo
  traffic carries a `demo_tag` and `/v1/admin/demo/reset` clears only tagged events;
  untagged real observations are never touched.
- **Unverified against real AWS:** the Textract response shape (the adapter follows the
  documented API but has never been called), browser-to-S3 presigned PUT under the
  configured CORS rules, and Lambda cold-start latency with a 78 MB package. These are
  the first things to check after deploying.
- `tamper_reprint` is a documented confound, not a capability: a uniformly soft reprint
  trips the quality gate and returns UNABLE_TO_VERIFY. SCADS does not claim to detect
  that case. `tamper_resample` covers print degradation a sharp capture can establish.

## Environment checklist

- AWS region: `ap-south-1` (default; override with `AWS_REGION`)
- Amplify URL: **not yet deployed** — no credentials in this environment
- API base URL: **not yet deployed**
- S3 buckets: `scads-scans-{env}-{account}`, `scads-references-{env}-{account}`
- DynamoDB tables: `scads-registry-{env}`, `scads-scan-events-{env}`, `scads-references-{env}`
- Textract: `detect_document_text`, same region
- Bedrock: Claude 3.5 Haiku, off by default (`--bedrock` to enable)
- Deployment: `python scripts/deploy.py --region ap-south-1`
- Web deployment: `python scripts/deploy_web.py --api-url <ApiUrl>`
- Smoke test: `python scripts/smoke_test.py --base-url <api> --expect-aws`
- Demo seed: `python scripts/seed_demo.py` (add `--aws` for a deployed stack)
- Local dev: `python scripts/dev_server.py`

## Last verified test state

`313 passed` via `.venv/bin/python -m pytest tests/ -q`. No known failures.

Five consecutive demo rehearsals against a running server: 20/20 checks passed,
p50 370 ms. `scripts/secret_scan.py` clean. Lambda package builds at 78 MB unzipped.

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

Deploy. Everything else is done and verified locally.

```bash
export AWS_REGION=ap-south-1
.venv/bin/python scripts/deploy.py --plan     # review the change set first
.venv/bin/python scripts/deploy.py            # apply, seed, smoke test
.venv/bin/python scripts/deploy_web.py --api-url <ApiUrl from the output>
```

Then: open the Amplify URL in a private window, run the three demo packs, restrict
CORS to that origin (`scripts/deploy.py --allowed-origins <url>`), tag the commit, and
record the video against `docs/DEMO_AND_SUBMISSION.md` section 2.

Unverified until then: the real Textract response shape against the pack fixtures
(the adapter is written to the documented API but has never been called), S3 presigned
PUT from a browser with the CORS rules as configured, and Lambda cold-start latency
with a 78 MB package.

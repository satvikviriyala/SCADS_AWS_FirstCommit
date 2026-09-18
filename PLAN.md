# PLAN.md — End-to-end execution plan

## 0. Strategy

The project has two simultaneous goals:

1. **Win the weekend on execution:** one reliable AWS-deployed vertical slice with a memorable demonstration.
2. **Show depth without building a science-fiction system:** encode the future architecture in data models, event semantics and a visible history-anomaly signal.

The plan therefore separates:

- **P0:** required for submission.
- **P1:** high-value differentiation if P0 is stable.
- **P2:** roadmap only; document or prototype only after P0/P1.

## 1. Critical product hypothesis

A counterfeit-risk system is stronger when it combines independent evidence:

- Is the claimed identity recognized?
- Does the physical package match an enrolled reference under controlled comparison?
- Does this scan make sense given prior scans and lifecycle history?
- Is the product itself currently valid (not expired/recalled/withdrawn)?

The system must expose contradictions rather than average them away.

## 2. Phase graph

```text
0 Foundation
   |
1 Deployed vertical slice
   |
2 Identity registry + extraction
   |
3 Physical comparison
   |
4 History anomaly + fusion
   |
5 UX + explanation
   |
6 Evaluation + hardening
   |
7 Submission + demo
   |
8 Post-hackathon roadmap (P2)
```

Do not parallelize dependencies that produce incompatible contracts.

---

# Phase 0 — Foundation [P0]

Detailed file: `phases/PHASE_0_FOUNDATION.md`

### Outputs
- repository structure;
- shared TypeScript/Python contracts;
- local environment;
- AWS account/region config;
- SAM/CDK skeleton;
- CI/basic checks;
- `.env.example`;
- first `MEMORY.md` update.

### Exit gate
A minimal frontend and `/health` endpoint build locally, tests run, no secrets committed.

---

# Phase 1 — Deployed vertical slice [P0]

Detailed file: `phases/PHASE_1_VERTICAL_SLICE.md`

### Objective
Prove the full path before sophisticated detection.

### Outputs
- Amplify URL;
- API Gateway endpoint;
- private S3 bucket;
- presigned upload endpoint;
- scan creation endpoint;
- DynamoDB scan record;
- response rendered on frontend;
- CloudWatch logs.

### Exit gate
A phone can upload an image to deployed AWS, invoke the backend, persist an event and see a result.

This must work before feature engineering.

---

# Phase 2 — Identity registry and extraction [P0]

Detailed file: `phases/PHASE_2_IDENTITY.md`

### Outputs
- registry schema;
- seeded manufacturer/product/batch/unit records;
- QR decoding;
- Textract OCR extraction fallback;
- deterministic normalization;
- registry lookup;
- expiry/recall state;
- reason codes;
- tests.

### Exit gate
Fixtures for:
- valid serial;
- unknown serial;
- valid batch without serial;
- expired batch;
- revoked/flagged serial
produce correct structured outcomes.

---

# Phase 3 — Physical packaging comparison [P0]

Detailed file: `phases/PHASE_3_PHYSICAL.md`

### Outputs
- quality gate;
- reference-image enrollment metadata;
- geometric registration;
- ROI configuration;
- OCR text/layout similarity;
- structural similarity;
- edge/print-sharpness comparison;
- physical feature vector + confidence;
- deterministic diagnostics.

### Exit gate
Clean fixture passes; deliberately tampered fixture degrades expected features; low-quality capture returns `UNABLE_TO_VERIFY`.

---

# Phase 4 — Scan history and fusion [P0]

Detailed file: `phases/PHASE_4_HISTORY_AND_FUSION.md`

### Outputs
- scan-event query by serial;
- duplicate/reuse rule;
- impossible-travel rule over synthetic/coarse locations;
- post-sale reuse/lifecycle rule;
- pure fusion engine;
- hard caps for severe contradictions;
- reason-code ordering;
- audit fields.

### Exit gate
The three demo scenarios are all deterministic and covered by automated tests.

This is the minimum distinctive SCADS product.

---

# Phase 5 — UX and explanation [P0/P1]

Detailed file: `phases/PHASE_5_UX.md`

### P0
- camera/upload flow;
- scan-quality feedback;
- result state;
- score dimensions;
- reason codes translated to plain language;
- “what to do next” safe guidance;
- retry flow;
- responsive UI.

### P1
- tamper slider / controlled synthetic demo panel;
- visual overlays showing matched/mismatched regions;
- history timeline visualization;
- architecture drawer.

### Exit gate
A first-time user understands the result without being told what each number means.

---

# Phase 6 — Evaluation, hardening and operations [P0/P1]

Detailed file: `phases/PHASE_6_EVALUATION.md`

### P0
- unit/integration tests;
- synthetic fixture generator;
- decision-policy tests;
- basic latency measurements;
- failure-mode tests;
- logs/metrics;
- seed/reset script.

### P1
- ablations;
- false-positive stress tests;
- multiple devices/lighting;
- reference versioning;
- calibration notebook/report;
- WAF/rate-limit if quick.

### Exit gate
A demo can be reset and repeated at least 5 times with predictable results.

---

# Phase 7 — Submission [P0]

Detailed file: `phases/PHASE_7_SUBMISSION.md`

### Outputs
- public repository;
- public working URL;
- <=3-minute video;
- short writeup;
- architecture diagram;
- clear AWS service proof;
- learning section;
- attribution/license audit;
- screenshots;
- final README;
- early submission followed by safe improvements.

### Exit gate
Another person can open the submission, watch only the video and understand:
1. problem;
2. why QR alone fails;
3. what SCADS does;
4. that it actually works;
5. how AWS is used;
6. what is novel/different in the project’s framing.

---

# Phase 8 — Post-hackathon [P2]

Detailed file: `phases/PHASE_8_POST_HACKATHON.md`

Do not implement at the cost of submission.

Includes:
- manufacturer enrollment at line speed;
- cryptographically signed identifiers;
- unit serialization;
- copy-detection patterns / PUF-like physical fingerprints;
- EPCIS 2.0 event interchange;
- stream/graph anomaly detection;
- pharmacy/distributor/route risk;
- recalls/adverse event integration;
- regulator dashboard;
- offline-first field verification;
- privacy-preserving analytics;
- calibration on seized/adjudicated counterfeit samples;
- chemical/spectroscopic partner integrations where appropriate.

---

# 3. Priority stack

## P0: must work
- live AWS URL;
- upload;
- seeded registry;
- OCR/QR extraction;
- physical comparison;
- duplicate/impossible-travel history anomaly;
- fusion/reason codes;
- 3 demo scenarios;
- tests;
- reset script;
- video/writeup.

## P1: add if stable
- tamper slider;
- mismatch overlays;
- Bedrock result explanation;
- richer anomaly timeline;
- Cognito admin;
- better CI;
- latency dashboard;
- signed demo QR payload.

## P2: document, not build now
- GNNs;
- Neptune graph;
- full EPCIS ingestion;
- blockchain;
- NFC;
- spectroscopy;
- nationwide regulator integration;
- model training infrastructure;
- on-dose PUF;
- pharmacy reputation model.

---

# 4. Architecture acceptance tests

The system is not done merely because the UI produces scores.

### AT-01 Valid pack
Given an enrolled reference, valid identity and no contradictory history, output is not suspicious.

### AT-02 Unknown identity
Unknown serial/batch cannot be rescued by perfect visual similarity.

### AT-03 Visual tamper
Known identity cannot fully mask a strong physical mismatch.

### AT-04 Quality failure
Blur/glare/occlusion below quality floor yields `UNABLE_TO_VERIFY`.

### AT-05 Serial clone
A physically perfect package carrying a reused serial is capped as suspicious.

### AT-06 Impossible travel
Two events separated by an impossible distance/time produce the configured anomaly.

### AT-07 Expiry is separate
Expired but otherwise matching pack reports product status separately; do not mislabel expiry as counterfeit evidence.

### AT-08 Explanation consistency
User-facing prose cannot contradict structured reason codes.

### AT-09 Reproducibility
Same evidence + same pipeline/policy version => same decision.

### AT-10 Evidence audit
Every scan persists pipeline version, policy version, reference version, signal values and reason codes.

---

# 5. Delivery risks and fallback ladder

## If Textract is slow
1. direct QR decode;
2. local OCR library in CV worker;
3. Textract only when QR/direct extraction fails.

## OpenCV packaging [RESOLVED — OpenCV was removed]

Measured rather than assumed: opencv-python-headless + numpy unzips to 223 MB
against a 250 MB Lambda limit, carrying two copies of OpenBLAS and the ffmpeg
stack for three function calls. numpy + Pillow is 79 MB and deploys as a plain
zip with no Docker in the build path.

Registration now uses quadrilateral detection plus a four-point DLT homography,
which suits a planar carton better than ORB in any case. QR decoding moved to
the browser's `BarcodeDetector`, with Textract OCR of the printed serial as the
fallback. See `docs/ARCHITECTURE.md` section 5.

If a future feature genuinely needs heavier CV, go to App Runner rather than a
Lambda container.

## If Bedrock access/region fails
Remove it from the request-critical path. Use deterministic explanation templates.

## If browser camera permissions fail
Keep file upload as first-class fallback.

## If geolocation permission is blocked
Use a clearly labelled synthetic demo-location selector for anomaly demonstration. Never fake collection of real location.

## If time becomes critical
Protect these in order:
1. deployed scan path;
2. identity;
3. physical mismatch;
4. cloned serial history;
5. result explanation;
6. everything else.

---

# 6. Success metrics

Hackathon engineering success:
- >95% successful demo request completion in rehearsal;
- p50 scan result target <5s if synchronous, or responsive progress if async;
- deterministic three scenario behavior;
- no critical secrets in repo;
- no broken public URL;
- no misleading authenticity claims.

Research/product success later:
- calibrated sensitivity/specificity on real labeled counterfeit/genuine packs;
- false-positive rate stratified by device/lighting/product;
- clone detection precision/recall;
- time to anomaly;
- investigation yield per alert;
- adoption and successful verification rate.

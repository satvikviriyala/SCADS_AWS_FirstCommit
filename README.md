# SCADS — Supply-Chain-Aware Drug Screening

SCADS is a phone-first counterfeit-medicine risk screening and pharmaceutical supply-chain intelligence system.

The hackathon wedge is deliberately narrow and demonstrable:

> **Do not ask only “does this QR/batch exist?” Ask “does this physical pack, with this identity, make sense in this place and scan history?”**

The First Commit MVP combines:

1. **Identity evidence** — QR/OCR-extracted product/batch/serial information checked against a trusted registry.
2. **Physical packaging evidence** — image quality gating, geometric registration, OCR-layout consistency, structural similarity, edge/print-sharpness checks, and optional copy-sensitive regions.
3. **Scan-history evidence** — duplicate serial reuse, post-sale reuse, impossible-travel/location contradictions, and lifecycle inconsistencies.
4. **Transparent fusion** — hard contradiction gates + a multiplicative/geometric fusion rather than a simple average.
5. **Reason codes** — the user sees why a pack is low observed risk, suspicious, or unable to verify.

The long-term system grows from this wedge into factory enrollment, unit-level serialization, physical fingerprints / copy-detection patterns, EPCIS-compatible custody events, graph anomaly detection, route/pharmacy risk, regulatory alerts, adverse-event feedback, and offline-first verification.

## Safety and claim boundary

SCADS is **not a chemical assay**. A phone image cannot prove active ingredient, potency, sterility, dissolution, contamination status, or chemical composition. The product must therefore use language such as:

- `LOW_OBSERVED_RISK`
- `REVIEW_REQUIRED`
- `SUSPICIOUS`
- `UNABLE_TO_VERIFY`

Do **not** display “100% genuine”, “safe to consume”, or equivalent claims.

## Repository map

Read in this order:

- `CLAUDE.md`
- `AGENTS.md`
- `MEMORY.md`
- `PLAN.md`
- `docs/PRODUCT_VISION.md`
- `docs/ARCHITECTURE.md`
- `docs/API_CONTRACTS.md`
- `docs/DATA_MODEL.md`
- `docs/SCORING_AND_DETECTION.md`
- `docs/THREAT_MODEL.md`
- `docs/AWS_DEPLOYMENT.md`
- `docs/SECURITY_PRIVACY.md`
- `docs/EVALUATION.md`
- `docs/DEMO_AND_SUBMISSION.md`
- `docs/ROADMAP.md`
- `docs/RESEARCH_NOTES.md`
- `phases/*`
- `MASTER_PROMPT.md`

## Hackathon objective

Target the **Ship It** track with a live AWS URL and architecture that visibly uses AWS for the actual request path. Build one excellent end-to-end flow before adding breadth.

The decisive demo sequence should be:

1. Scan a seeded genuine pack → identity + visual + history agree.
2. Scan a visually tampered image with a valid identity → physical evidence fails.
3. Scan a visually perfect clone carrying a previously-used serial → history evidence fails.
4. Show the result explanation and the AWS architecture / telemetry.

That third case is the conceptual leap beyond ordinary QR verification.

## Proposed stack

- Frontend: React/Next.js or Vite React, mobile-first PWA
- Hosting: AWS Amplify Hosting
- API: Amazon API Gateway
- Orchestration: AWS Lambda
- Image upload: Amazon S3 via pre-signed URL
- OCR / text boxes: Amazon Textract
- Optional multimodal normalization/explanation: Amazon Bedrock
- Registry + scan events + alerts: Amazon DynamoDB
- CV: OpenCV + scikit-image packaged in a Lambda container image, or a small App Runner service if Lambda packaging/latency becomes a blocker
- Events/async expansion: EventBridge / SQS
- Auth for admin/manufacturer tooling: Cognito
- Observability: CloudWatch
- IaC: AWS SAM or CDK; prefer SAM if it gets the team to a deployable vertical slice faster

## Status

Planning package complete. Implementation status must be kept in `MEMORY.md`.

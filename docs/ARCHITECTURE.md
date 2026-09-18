# SCADS Architecture

## 1. Architectural principles

1. **Evidence, not magic score.** Preserve individual signals and reason codes.
2. **Contradictions dominate averages.** Unknown/revoked/cloned identities cannot be washed out by a pretty image.
3. **Uncertainty is explicit.** Poor input yields `UNABLE_TO_VERIFY`.
4. **Event-first.** Every verification creates a scan event.
5. **Unit-first schema.** `serial -> batch -> SKU -> manufacturer`, with batch fallback.
6. **Auditable.** Store algorithm/policy/reference versions.
7. **Phone-first, cloud-backed.**
8. **AWS-native but not service-count driven.**
9. **Future-compatible with standard event interchange.**
10. **No chemical-authenticity claim from packaging evidence.**

---

## 2. Hackathon logical architecture

```mermaid
flowchart LR
    U[Phone / PWA] -->|1 request presigned upload| API[API Gateway]
    API --> L1[Scan API Lambda]
    L1 --> S3[(Private S3)]
    U -->|2 image upload| S3
    U -->|3 create scan| API

    U --> QR[QR decode\nbrowser BarcodeDetector]
    L1 --> TX[Amazon Textract]
    L1 --> CV[CV pipeline\nnumpy + Pillow, in-process]
    L1 --> DDB[(DynamoDB)]

    TX --> EXT[Metadata normalizer]
    QR -->|qr_payload| L1
    EXT --> DDB

    CV --> REF[(S3 Reference Images)]
    CV --> SIG[Physical feature vector]

    DDB --> HIST[History anomaly rules]
    EXT --> ID[Identity evaluator]
    ID --> FUSE[Decision Engine]
    SIG --> FUSE
    HIST --> FUSE
    FUSE --> DDB
    FUSE -->|structured result| API
    API --> U

    FUSE -. optional explanation .-> BR[Amazon Bedrock]
    BR -. safe prose .-> U

    L1 --> CW[CloudWatch]
    CV --> CW
```

### Important correction from the initial concept

Bedrock is not the required OCR/authenticity engine.

For the core verdict:
- QR parsing is deterministic.
- Textract returns text/bounding boxes.
- CV computes deterministic features.
- DynamoDB provides registry/history.
- the decision engine is a pure function.

Bedrock can be used for:
- field normalization when OCR is ambiguous;
- safe explanation from already-decided reason codes;
- admin tooling.

If Bedrock fails, SCADS still verifies.

---

## 3. Request flow

### 3.1 Create upload

`POST /v1/uploads`

Backend validates:
- MIME allowlist;
- max size;
- expected scan id;
- authenticated admin-only fields not exposed.

Returns:
- `scan_id`;
- presigned S3 `PUT` URL;
- object key.

### 3.2 Upload image

Phone uploads directly to S3, reducing API Gateway/Lambda payload burden.

Object key example:

```text
scans/2026/09/18/{scan_id}/original.jpg
```

S3 stays private.

### 3.3 Start analysis

`POST /v1/scans/{scan_id}/analyze`

Input may include:
- parsed QR payload from client;
- optional coarse/demo location;
- explicit consent flags;
- product hint only if needed.

### 3.4 Extraction

Order:
1. decode QR if available;
2. verify payload schema/signature if supported;
3. call Textract when visible text is required;
4. normalize batch/lot/date/manufacturer;
5. cross-check QR claims against OCR-visible claims.

### 3.5 Registry lookup

Lookup in unit registry:
- serial;
- batch;
- SKU;
- manufacturer;
- status;
- reference profile version.

Fallback to batch-only mode if demo product has no serial.

### 3.6 Physical comparison

Before comparison:
1. quality gate;
2. detect package/ROI;
3. align to reference using feature matches/homography;
4. compute feature set only if alignment confidence passes.

Feature outputs include:
- text-content similarity;
- text-layout similarity;
- SSIM / structural similarity on stable ROIs;
- edge/sharpness statistics;
- optional color consistency;
- registration quality.

### 3.7 History analysis

Query prior events by serial.

Rules:
- serial reused;
- already decommissioned/sold then reused;
- impossible travel;
- excessive scan velocity;
- conflicting product/batch claims.

For demo, the minimum is duplicate + impossible travel.

### 3.8 Decision

Use `docs/SCORING_AND_DETECTION.md`.

The engine returns:
- dimensions;
- decision;
- trust presentation score;
- reason codes;
- next action;
- versions.

### 3.9 Explanation

Frontend maps reason codes to deterministic text.

Optional Bedrock prompt receives **only** structured outcome, never arbitrary authority:

```json
{
  "decision": "SUSPICIOUS",
  "reason_codes": ["SERIAL_REUSE", "IMPOSSIBLE_TRAVEL"],
  "dimensions": {"identity": 0.95, "physical": 0.91, "history": 0.18}
}
```

It may rewrite for readability, but it may not change the decision.

---

## 4. Sync vs async

### MVP
Prefer synchronous orchestration if end-to-end latency is acceptable.

### Fallback
If Textract/CV latency causes timeout:
- create scan => `PROCESSING`;
- S3 event or API call triggers Step Functions/Lambda;
- frontend polls `GET /v1/scans/{scan_id}` with bounded backoff.

Do not add Step Functions solely for architecture theatre.

---

## 5. CV compute placement

**Decided: a plain Lambda zip, numpy + Pillow only.** No container image, no App
Runner, no OpenCV.

The original plan preferred a Lambda container image because OpenCV was assumed
necessary. Measuring the actual packages changed the decision:

| Dependency set | Unzipped | Fits a Lambda zip? |
|---|---|---|
| numpy + opencv-python-headless + Pillow | 223 MB | 27 MB under a 250 MB hard limit |
| numpy + Pillow | 79 MB | comfortably |

The OpenCV build carries two separate copies of OpenBLAS (~71 MB together) and
the full ffmpeg stack, for code that only needed `imdecode`, ORB and
`warpPerspective`. Meanwhile the documented container fallback could not be
built or validated at all, because the development environment has no Docker.

What replaced OpenCV:

| Needed | Now |
|---|---|
| decode JPEG/PNG | Pillow |
| Gaussian blur | separable float convolution in numpy |
| SSIM | implemented directly (~15 lines over a Gaussian) |
| ORB + RANSAC homography | quadrilateral detection + four-point DLT homography |
| `QRCodeDetector` | browser `BarcodeDetector`, with Textract OCR of the printed serial as fallback |

The registration change is an improvement rather than a compromise. A medicine
carton is a planar rectangle, which is far stronger prior information than
generic keypoints exploit: locating its four corners by fitting the four edges
and solving the exact four-point homography is more robust on low-texture
artwork than descriptor matching, and fully deterministic.

### Decision rule going forward

Keep the detection package to numpy + Pillow. Adding a dependency that
reintroduces a container build must be justified against a measured
capability gain, because the container path costs Docker in CI, a registry, and
cold-start weight.

### If a future feature genuinely needs heavier CV

Then App Runner with a FastAPI service, per the original fallback — not a
Lambda container, since at that point the size pressure is real rather than
incidental.

## 6. Reference enrollment

Hackathon enrollment can be CLI/admin-only.

For each product/package variant store:

```text
reference_profile_id
sku_id
packaging_variant
reference_version
reference_image_s3_key
stable_rois[]
ocr_anchors[]
expected_dimensions/aspect
feature_baselines
created_at
```

Use multiple genuine captures if available.

Never compare an arbitrary phone photo directly to an unregistered web product image and call the delta counterfeit evidence.

---

## 7. Future architecture

```mermaid
flowchart TB
    MFG[Manufacturer Packaging Line] --> SER[Serial issuer + signed identity]
    MFG --> FP[Physical fingerprint enrollment]
    SER --> EV[Event Bus / EPCIS gateway]
    FP --> OBJ[(Fingerprint store)]

    DIST[Distributor / Pharmacy Events] --> EV
    CON[Consumer Scans] --> EV
    REG[Regulator / Recall Feeds] --> EV
    AE[Adverse Event Signals] --> EV

    EV --> LAKE[(Event lake)]
    EV --> STREAM[Stream anomaly engine]
    LAKE --> GRAPH[Supply-chain graph features]
    GRAPH --> RISK[Entity / route / cluster risk]
    STREAM --> RISK
    OBJ --> VERIFY[Physical verifier]
    SER --> VERIFY

    VERIFY --> DEC[Evidence fusion]
    RISK --> DEC
    DEC --> CASE[Investigation / alert workflow]
```

Future platform components can include:
- Kinesis/EventBridge;
- S3 data lake;
- Glue/Athena;
- OpenSearch;
- Neptune only if graph traversal requirements justify it;
- SageMaker for calibrated models;
- EPCIS adapters;
- regulator/manufacturer APIs.

Do not introduce these during the weekend unless the core path is already finished.

---

## 8. Failure semantics

| Failure | Result |
|---|---|
| Image too blurry/glared | `UNABLE_TO_VERIFY` |
| Unsupported SKU/reference missing | `UNABLE_TO_VERIFY` |
| Unknown serial but batch exists | `REVIEW_REQUIRED` or `SUSPICIOUS` per policy, never low-risk solely on image |
| Serial revoked | `SUSPICIOUS` |
| Perfect image + cloned serial | `SUSPICIOUS` |
| Valid identity + physical mismatch | `SUSPICIOUS` / `REVIEW_REQUIRED` |
| Expired authentic pack | authenticity dimensions can be high, `product_status=EXPIRED`; UI warns not to use |
| Bedrock unavailable | deterministic explanation fallback; core decision unaffected |

---

## 9. Architecture invariants

- No public S3 buckets.
- Consumer cannot enroll/update genuine references.
- Consumer cannot set unit status.
- Scan history is not destructively rewritten.
- Exact location is not required.
- All thresholds are versioned.
- Result always reports quality and evidence dimensions.

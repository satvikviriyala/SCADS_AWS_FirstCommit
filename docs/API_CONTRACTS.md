# API Contracts

Use a shared schema package and generate/validate types where possible.

Base path: `/v1`

## 1. `POST /uploads`

Create a scan and an upload target.

Request:

```json
{
  "content_type": "image/jpeg",
  "content_length": 1320442,
  "sha256": "optional-client-hash"
}
```

Response:

```json
{
  "scan_id": "scn_01...",
  "upload": {
    "method": "PUT",
    "url": "<presigned>",
    "headers": {"Content-Type": "image/jpeg"},
    "expires_in_seconds": 300
  },
  "object_key": "scans/.../original.jpg"
}
```

Errors:
- `UNSUPPORTED_MEDIA_TYPE`
- `FILE_TOO_LARGE`
- `RATE_LIMITED`

## 2. `POST /scans/{scan_id}/analyze`

Request:

```json
{
  "qr_payload": "optional raw QR payload",
  "location": {
    "mode": "DEMO|COARSE|NONE",
    "label": "Bengaluru",
    "lat_bucket": 12.9,
    "lon_bucket": 77.6
  },
  "consent": {
    "coarse_location": false
  }
}
```

For the hackathon, `DEMO` locations may be synthetic scenario inputs. UI must label them as simulation.

Response:

```json
{
  "scan_id": "scn_01...",
  "status": "COMPLETED",
  "decision": "LOW_OBSERVED_RISK",
  "presentation_score": 0.88,
  "dimensions": {
    "identity_score": 0.96,
    "physical_score": 0.86,
    "history_score": 0.94,
    "scan_quality": 0.91
  },
  "product_status": {
    "state": "ACTIVE",
    "expiry_date": "2027-08-31",
    "recall_status": "NONE"
  },
  "identity": {
    "manufacturer_id": "mfg_demo_1",
    "sku_id": "sku_demo_1",
    "batch_id": "batch_demo_1",
    "serial_id": "serial_demo_001",
    "verification_level": "UNIT"
  },
  "reason_codes": [
    "IDENTITY_VALID",
    "PHYSICAL_MATCH",
    "NO_HISTORY_CONTRADICTION"
  ],
  "evidence": {
    "reference_version": "ref_v1",
    "pipeline_version": "cv_0.1.0",
    "fusion_policy_version": "fusion_0.1.0"
  },
  "next_action": "No configured contradiction was observed. This scan does not test chemical contents."
}
```

## 3. `GET /scans/{scan_id}`

Used for async fallback.

States:
- `CREATED`
- `UPLOADED`
- `PROCESSING`
- `COMPLETED`
- `FAILED`

Never expose internal stack traces.

## 4. `GET /health`

Return deployment metadata safe for public display:

```json
{
  "ok": true,
  "service": "scads-api",
  "version": "0.1.0"
}
```

No AWS account ids or secrets.

## 5. Admin-only demo endpoints

Prefer CLI seed scripts over public mutation endpoints.

If a demo endpoint exists, protect it using Cognito/admin secret and disable after submission.

Potential endpoint:

`POST /admin/demo/reset`

Purpose:
- reset seeded scan events;
- reinsert known history fixture.

Never allow unauthenticated reset of registry/history.

---

# Decision enum

```text
LOW_OBSERVED_RISK
REVIEW_REQUIRED
SUSPICIOUS
UNABLE_TO_VERIFY
```

# Verification level enum

```text
NONE
PRODUCT
BATCH
UNIT
```

# Product status enum

```text
ACTIVE
EXPIRED
RECALLED
WITHDRAWN
UNKNOWN
```

# Reason-code registry

## Input/quality
- `IMAGE_TOO_BLURRY`
- `IMAGE_OVEREXPOSED`
- `IMAGE_UNDEREXPOSED`
- `PACKAGE_OCCLUDED`
- `REGISTRATION_FAILED`
- `UNSUPPORTED_PACKAGE_VARIANT`

## Identity
- `IDENTITY_VALID`
- `BATCH_VALID`
- `SERIAL_UNKNOWN`
- `BATCH_UNKNOWN`
- `SERIAL_REVOKED`
- `QR_OCR_CONFLICT`
- `IDENTITY_PARSE_FAILED`

## Physical
- `PHYSICAL_MATCH`
- `TEXT_CONTENT_MISMATCH`
- `TEXT_LAYOUT_MISMATCH`
- `STRUCTURAL_MISMATCH`
- `PRINT_SHARPNESS_MISMATCH`
- `COLOR_MISMATCH`
- `COPY_PATTERN_MISMATCH`

## History
- `NO_HISTORY_CONTRADICTION`
- `SERIAL_REUSE`
- `IMPOSSIBLE_TRAVEL`
- `POST_SALE_REUSE`
- `SCAN_VELOCITY_ANOMALY`
- `LIFECYCLE_CONFLICT`

## Product status
- `PRODUCT_EXPIRED`
- `PRODUCT_RECALLED`

## System
- `REFERENCE_NOT_FOUND`
- `ANALYSIS_TIMEOUT`
- `DEPENDENCY_UNAVAILABLE`

Reason codes are API contract. Do not rename casually.

---

# Contract rules

1. `UNABLE_TO_VERIFY` requires at least one quality/system reason.
2. A severe identity/history contradiction cannot return `LOW_OBSERVED_RISK`.
3. Product expiry/recall is not silently blended into authenticity.
4. `presentation_score` is optional UI sugar; `dimensions` + `reason_codes` are authoritative.
5. A Bedrock-generated explanation may not add reason codes that the engine did not produce.

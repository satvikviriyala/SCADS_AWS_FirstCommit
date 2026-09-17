# Data Model

## 1. Goals

- support hackathon lookups with minimal complexity;
- preserve unit-level evolution;
- make scan history first-class;
- keep data compatible with later event standards and graph analysis;
- avoid a mutable `verified=true` anti-pattern.

## 2. Logical entities

```text
Manufacturer
  -> Product/SKU
      -> PackagingVariant
      -> Batch
          -> UnitSerial

ReferenceProfile -> Product/SKU + PackagingVariant
ScanEvent -> UnitSerial/Batch + observed evidence
Finding -> ScanEvent
LifecycleEvent -> UnitSerial/Batch
```

## 3. MVP DynamoDB layout

Prefer understandable tables over premature single-table cleverness.

### `scads_registry`

Primary key:
- `pk`
- `sk`

Examples:

```text
PK=MFG#mfg_1       SK=META
PK=SKU#sku_1       SK=META
PK=BATCH#batch_1   SK=META
PK=SERIAL#ser_001  SK=META
```

Fields for serial:

```json
{
  "pk": "SERIAL#ser_001",
  "sk": "META",
  "serial_id": "ser_001",
  "batch_id": "batch_1",
  "sku_id": "sku_1",
  "manufacturer_id": "mfg_1",
  "status": "ACTIVE",
  "issued_at": "...",
  "decommissioned_at": null,
  "reference_profile_id": "ref_1"
}
```

Batch:

```json
{
  "pk": "BATCH#batch_1",
  "sk": "META",
  "batch_id": "batch_1",
  "sku_id": "sku_1",
  "mfg_date": "2026-07-01",
  "expiry_date": "2027-07-01",
  "status": "ACTIVE"
}
```

### `scads_scan_events`

Primary:
- `scan_id`

GSI1:
- `serial_id`
- `event_time`

GSI2:
- `batch_id`
- `event_time`

Event:

```json
{
  "scan_id": "scn_...",
  "event_time": "2026-09-18T10:00:00Z",
  "serial_id": "ser_001",
  "batch_id": "batch_1",
  "sku_id": "sku_1",
  "actor_type": "CONSUMER",
  "location_mode": "DEMO",
  "location_bucket": "BLR",
  "image_s3_key": "scans/.../original.jpg",
  "decision": "SUSPICIOUS",
  "presentation_score": 0.19,
  "identity_score": 0.97,
  "physical_score": 0.94,
  "history_score": 0.11,
  "scan_quality": 0.91,
  "reason_codes": ["SERIAL_REUSE", "IMPOSSIBLE_TRAVEL"],
  "pipeline_version": "cv_0.1.0",
  "fusion_policy_version": "fusion_0.1.0",
  "reference_version": "ref_v1"
}
```

### `scads_reference_profiles`

Primary:
- `reference_profile_id`

Fields:

```json
{
  "reference_profile_id": "ref_1",
  "sku_id": "sku_1",
  "packaging_variant": "BLISTER_FRONT_v1",
  "version": "ref_v1",
  "image_s3_key": "references/sku_1/v1/front.jpg",
  "aspect_ratio": 1.72,
  "stable_rois": [...],
  "ocr_anchors": [...],
  "feature_baselines": {...}
}
```

### `scads_alerts` [optional MVP/P1]

Persist severe findings for an admin timeline.

---

## 4. Identifiers

Internal IDs should not expose business semantics unnecessarily.

Use prefixes:
- `mfg_`
- `sku_`
- `batch_`
- `ser_`
- `ref_`
- `scn_`
- `alert_`

External GS1 identifiers can later be attached:
- GTIN
- SGTIN
- SSCC
- GLN

Do not force a fake GS1 mapping onto demo data.

---

## 5. Scan event semantics

A scan is an observation, not a truth mutation.

Events should contain:
- when;
- what identity was claimed;
- what identity was resolved;
- where at coarse granularity if authorized;
- actor type;
- evidence;
- decision;
- algorithm versions.

A later correction should add:
- adjudication event;
- investigation outcome;
- label.

Do not rewrite the original observation.

---

## 6. Lifecycle

Suggested unit lifecycle:

```text
COMMISSIONED
PACKED
SHIPPED
RECEIVED
DISPENSED
DECOMMISSIONED
RECALLED
DESTROYED
```

Hackathon may only seed:
- `COMMISSIONED`
- `DISPENSED`

History rules must be written so additional states can be added later.

---

## 7. EPCIS evolution

GS1 EPCIS represents “what, when, where, why/how” visibility events across supply chains.

SCADS should preserve enough semantics to map later:

```text
SCADS ScanEvent
  event_time      -> EPCIS eventTime
  serial/GTIN     -> what
  coarse location -> readPoint / bizLocation
  actor/process   -> bizStep/disposition
  lifecycle       -> disposition
```

Do not implement full EPCIS 2.0 during the hackathon unless required by an integration.

---

## 8. Privacy

Never store:
- person name;
- phone;
- Aadhaar;
- exact GPS by default;
- raw EXIF if not required.

For anomaly demo, use named synthetic location buckets.

Production design can use privacy-preserving geohash/coarse cells with consent and retention rules.

---

## 9. Data retention

Hackathon:
- raw uploads can expire using S3 lifecycle after a short configured period;
- scan metadata retained for demo/evaluation.

Production:
- tier retention by purpose;
- decouple investigative evidence from consumer telemetry;
- support deletion/privacy policy subject to regulatory retention obligations.

---

## 10. Seed fixtures

Minimum:

### Product A
- `sku_demo_a`
- batch valid
- serial `SER-A-001`
- reference image A

### Product B
- second visual reference to prove system is not hardcoded to one pack

### History clone fixture
Prior event:
- `SER-A-CLONE`
- location `DELHI_DEMO`
- time `T-60min`
Current demo:
- same serial
- `BENGALURU_DEMO`
- identical/good image
Expected severe history finding.

# Scoring and Detection

## 1. Core philosophy

Do not train or tune a magic scalar first.

SCADS computes independent evidence dimensions, applies contradiction gates, and only then derives a presentation score.

Dimensions:

```text
Q = scan quality
I = identity evidence
P = physical packaging evidence
H = scan/history evidence
S = product status (categorical, not authenticity)
```

The verdict is primarily a policy over evidence, not a generic classifier label.

---

## 2. Stage 0 — Input validation

Reject or mark unverifiable if:
- unsupported MIME;
- corrupted file;
- extreme dimensions;
- no visible package;
- payload too large;
- suspicious file type.

Strip/ignore unneeded EXIF.

---

## 3. Stage 1 — Scan quality gate

Quality features can include:

### Blur
Variance of Laplacian or equivalent high-frequency metric.

### Exposure
Fraction of near-black / near-white pixels.

### Resolution
Minimum usable pixels over package ROI.

### Glare
Large saturated areas in expected printed regions.

### Perspective
Estimated homography / package quadrilateral quality.

### Occlusion/crop
Key anchor/ROI visibility.

Compute:

```text
Q in [0,1]
```

Policy:
- if `Q < q_min`: `UNABLE_TO_VERIFY`.
- do not run aggressive mismatch penalties when registration evidence is weak.

This single design choice prevents many false counterfeit accusations.

---

## 4. Stage 2 — Geometric registration

A raw SSIM between two handheld photos is invalid as a primary signal.

Process:
1. detect/crop package;
2. grayscale + normalize as needed;
3. local features such as ORB/SIFT;
4. descriptor matching;
5. RANSAC homography;
6. warp scan to canonical reference;
7. calculate registration confidence.

If inlier count/ratio or reprojection error is poor:
- try fallback anchor-based registration;
- otherwise return `REGISTRATION_FAILED` -> `UNABLE_TO_VERIFY`.

---

## 5. Stage 3 — Identity extraction

Priority:
1. QR/barcode decode;
2. Textract OCR;
3. deterministic regex/normalization;
4. optional Bedrock normalization only when ambiguity remains.

Cross-check:
- QR batch vs printed batch;
- QR product vs visible brand;
- expiry;
- manufacturer.

A valid QR that disagrees with visible print should generate `QR_OCR_CONFLICT`.

---

## 6. Stage 4 — Physical features

Do not rely on one global feature.

### 6.1 OCR text content
Compare expected stable text:
- brand;
- generic name;
- manufacturer;
- strength;
- fixed labels.

Dynamic fields like batch/expiry are checked against registry rather than a static reference string.

Feature:
`p_text_content`.

### 6.2 Text layout
Textract bounding boxes normalized to package coordinates.

Compare expected anchor positions using:
- center displacement;
- box IoU;
- relative alignment.

Feature:
`p_text_layout`.

### 6.3 Structural similarity
SSIM or multi-scale structural comparison on aligned, stable ROIs.

Avoid dynamic QR/batch regions unless separately handled.

Feature:
`p_structure`.

### 6.4 Edge / print sharpness
Compare edge density and local high-frequency behavior within text/logo ROIs.

Potential features:
- Laplacian energy;
- Sobel edge density;
- line spread proxy;
- local contrast.

Feature:
`p_print`.

This catches some reprint/blur artifacts but must be calibrated across phones and lighting.

### 6.5 Color consistency [P1]
Use normalized color space and stable regions.

Feature:
`p_color`.

Treat carefully because white balance varies.

### 6.6 Copy-sensitive pattern / physical fingerprint [future]
A designated high-entropy printed region, natural substrate texture or PUF-like enrollment can produce a stronger physical binding.

Feature:
`p_fingerprint`.

---

## 7. Physical score

For MVP:

```text
P = weighted_geometric_mean(
    p_text_content,
    p_text_layout,
    p_structure,
    p_print
)
```

Example demonstration weights only:

```text
text content  0.20
text layout   0.25
structure     0.35
print         0.20
```

Formula:

```text
P = exp(sum_i w_i * log(max(eps, p_i)))
```

Why geometric:
- one weak independent signal lowers the total;
- a perfect feature cannot fully hide a catastrophic feature;
- still smoother than a hard minimum.

These are **demo policy values**, not validated clinical thresholds.

---

## 8. Identity score

Possible components:
- identifier exists;
- hierarchy consistent;
- status active;
- QR/OCR consistency;
- cryptographic signature later.

Do not use a continuous score to hide hard contradictions.

Example:

```text
unknown serial         -> severe contradiction
revoked serial         -> severe contradiction
valid unit             -> high
valid batch only       -> moderate, lower assurance level
QR/OCR conflict        -> penalty / review
```

Store `verification_level`.

---

## 9. History score

Rules first.

### H1 Serial reuse
Same unit serial appears in multiple independent scans.

Nuance:
Repeated consumer rescans are not automatically malicious. Include time/device/session context where available without invasive fingerprinting.

Hackathon can deliberately seed a known clone scenario.

### H2 Impossible travel

Compute Haversine distance between coarse/synthetic location centroids.

```text
required_speed = distance_km / delta_hours
```

If above configured maximum:
- `IMPOSSIBLE_TRAVEL`.

Do not claim the real-world threshold is scientifically calibrated in the demo.

### H3 Post-sale reuse
If unit state is decommissioned/dispensed and reappears unexpectedly:
- `POST_SALE_REUSE`.

### H4 Scan burst [P1]
Count distinct regions/devices over rolling window.

### H5 Lifecycle conflict [future]
Custody events violate expected sequence.

---

## 10. Fusion policy

### 10.1 Quality gate

```python
if Q < q_min:
    return UNABLE_TO_VERIFY
```

### 10.2 Severe contradiction caps

Example demo policy:

```text
SERIAL_REVOKED       => max presentation score 0.05
SERIAL_UNKNOWN*      => cannot be LOW_OBSERVED_RISK at UNIT level
IMPOSSIBLE_TRAVEL    => max 0.25
POST_SALE_REUSE      => max 0.25
strong QR/OCR conflict => max 0.35
```

`SERIAL_UNKNOWN` may degrade to batch-level verification if batch is valid; output must clearly say unit identity not verified.

### 10.3 Base score

```text
T_base = exp(
  wI * log(max(eps, I)) +
  wP * log(max(eps, P)) +
  wH * log(max(eps, H))
)
```

Demo weights:
- identity 0.35
- physical 0.40
- history 0.25

When history is unavailable for batch-only legacy mode, do not silently set H=1. Use a lower assurance profile and renormalize with an explicit `verification_level`.

### 10.4 Apply caps

```text
T = min(T_base, all_active_caps)
```

### 10.5 Decision thresholds

Temporary demo example:

```text
T >= 0.75 -> LOW_OBSERVED_RISK
0.45 <= T < 0.75 -> REVIEW_REQUIRED
T < 0.45 -> SUSPICIOUS
```

But hard policy may override.

Store threshold version.

---

## 11. Better future fusion

Once real labeled data exists:
- calibrate each feature probability;
- evaluate logistic/product-of-experts models;
- learn conditional dependencies;
- conformal prediction/uncertainty;
- per-product thresholds;
- hierarchical Bayesian calibration;
- cost-sensitive decision policy.

Never claim handcrafted weekend thresholds are production validated.

---

## 12. Visual explanation

For demo/UI:
- show aligned package;
- outline stable ROIs;
- green/yellow/red feature rows;
- show “identity”, “physical package”, “scan history” separately;
- keep numeric score secondary.

Example:

```text
Identity        96%   valid unit record
Physical        91%   expected layout and print structure
Scan history    18%   same serial seen far away 58 min earlier
Decision        SUSPICIOUS
```

This is more persuasive than a single 68% score.

---

## 13. Tests

Required:
- arithmetic average would pass but geometric fusion lowers result;
- severe history contradiction caps even with I=P=0.99;
- low Q returns unverifiable;
- expiry does not alter physical authenticity score;
- batch-only mode never presents same assurance language as unit-level;
- repeat same input => same output;
- floating-point edge cases;
- missing signal handled explicitly.

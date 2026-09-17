# Phase 3 — Physical Packaging Evidence

## Goal
Produce a reproducible physical evidence vector.

## Reference enrollment
For each demo product:
- take clean canonical image;
- define stable ROIs;
- exclude dynamic batch/expiry/QR from static SSIM where appropriate;
- store reference image in S3;
- seed metadata.

## Pipeline
1. decode image;
2. quality metrics;
3. crop/detect package;
4. feature registration/homography;
5. align;
6. OCR anchors;
7. layout similarity;
8. SSIM stable ROIs;
9. edge/sharpness;
10. physical score.

## Critical behavior
If quality or registration is inadequate:
`UNABLE_TO_VERIFY`.

## Synthetic fixtures
Generate:
- text shift;
- local blur/reprint proxy;
- recompression;
- structural patch;
- altered dynamic field.

## Tests
- original/reference high;
- alternate genuine capture acceptable;
- tampered ROI lower;
- blur below floor -> unverifiable.

## Acceptance
Demo fixture changes produce interpretable feature changes and overlays/logs.

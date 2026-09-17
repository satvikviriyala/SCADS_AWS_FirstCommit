# Evaluation Plan

## 1. What the hackathon evaluation can prove

It can prove:
- architecture works end to end;
- specific synthetic/controlled tampering changes expected features;
- cloned-identity scenarios trigger history rules;
- fusion logic behaves as designed;
- poor scans fail safely.

It cannot prove:
- national counterfeit prevalence;
- clinical safety;
- 90%+ real counterfeit detection;
- performance against sophisticated seized counterfeits without such a dataset.

Be explicit.

## 2. Fixture classes

### Genuine-reference captures
For each enrolled pack:
- canonical reference;
- alternate angle;
- alternate phone if possible;
- moderate lighting changes.

### Benign difficult captures
- mild blur;
- shadow;
- perspective;
- compression;
- partial background.

Goal: avoid false suspicion where the right output is pass or unverifiable.

### Synthetic tamper fixtures
Generate from genuine image:
- stronger blur/reprint proxy;
- JPEG recompression;
- local text shift;
- one batch digit modification;
- logo displacement;
- color cast;
- ROI replacement;
- local resampling.

Label them `synthetic_tamper`, not “real counterfeit”.

### Identity fixtures
- valid unit;
- unknown unit;
- revoked unit;
- valid batch only;
- QR/OCR mismatch.

### History fixtures
- first scan;
- same-region repeat;
- impossible travel;
- post-sale reuse;
- burst [P1].

## 3. Tamper slider

A strong demo tool if time permits.

Slider should control one or two interpretable perturbations:

```text
0.0 = original
1.0 = heavy perturbation
```

Recompute physical features and plot decline.

Do not imply monotonic slider == real counterfeit severity. It is a visualization of sensitivity.

## 4. Metrics

### Scan quality
- failure/retry rate;
- false unverifiable rate on acceptable images.

### Physical detection
On controlled fixtures:
- feature distributions;
- ROC/AUC only if sample size supports it;
- genuine-vs-synthetic-tamper separation;
- per-product results.

### Identity/history
Rules should have exact test truth.

### System
- end-to-end latency;
- error rate;
- p50/p95 if enough samples;
- cold-start behavior;
- upload time.

## 5. Ablation

Compare:
1. identity only;
2. physical only;
3. identity + physical;
4. identity + physical + history.

Use concrete scenario table:

| Scenario | Identity only | +Physical | +History |
|---|---|---|---|
| copied batch + poor fake print | may pass | caught | caught |
| perfect-looking clone + copied serial | may pass | may pass | caught |
| poor genuine photo | may pass identity | quality uncertain | quality uncertain |

This tells the story better than inflated accuracy claims.

## 6. Fusion unit tests

Minimum:
- one low feature depresses geometric mean more than arithmetic mean;
- hard cap always applies;
- unavailable history is not treated as perfect history;
- Q gate precedes counterfeit decision;
- exact boundary thresholds;
- NaN/None rejected;
- scores clamped [0,1].

## 7. CV regression tests

Use small fixed fixtures in repo where licensing/privacy permits.

Assert:
- registration succeeds;
- feature values within tolerant ranges;
- modified ROI causes expected change;
- low-quality fixture returns expected quality reason.

Do not assert fragile pixel-perfect floats.

## 8. Manual test matrix

Test at minimum:
- Chrome desktop;
- Chrome Android if available;
- mobile-width desktop simulation;
- camera vs upload;
- fresh cache/incognito;
- slow connection simulation if easy.

## 9. Rehearsal

Perform at least five full demo rehearsals.

Record:
- latency;
- any failed call;
- recovery;
- UI confusion;
- exact video duration.

Fix reliability before P1 features.

## 10. Future scientific evaluation

A serious publication/product pilot should use:
- manufacturer-approved genuine samples;
- adjudicated seized counterfeit samples;
- multiple phones;
- multiple production lots;
- cross-site lighting;
- packaging aging;
- blinded evaluation;
- predeclared thresholds;
- confidence intervals;
- calibration;
- failure analysis.

That is the path from hackathon prototype to credible detection system.

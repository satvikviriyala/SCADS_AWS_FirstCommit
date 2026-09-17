# Phase 5 — UX

## Goal
Make evidence understandable in seconds.

## Scan screen
- large camera/upload action;
- privacy note;
- supported-pack hint;
- image quality guidance.

## Processing
Show stages:
- reading identity;
- comparing package;
- checking scan history.

Do not fake progress if backend already returned.

## Result
Top decision.

Then:
1. Identity
2. Physical package
3. Scan history

Each card:
- state;
- short explanation;
- optionally score.

Then:
- product status;
- safe next step;
- limitation.

## P1 demo features
### Tamper slider
Controls synthetic image perturbation.

### Alignment/mismatch overlay
Judge can see what changed.

### History timeline
Two location/time cards demonstrating clone.

## Accessibility
- do not depend on red/green alone;
- large tap targets;
- readable mobile text;
- loading/error/retry.

## Acceptance
A person unfamiliar with architecture can explain why scenario C is suspicious.

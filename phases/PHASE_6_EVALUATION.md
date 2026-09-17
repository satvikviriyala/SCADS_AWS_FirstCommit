# Phase 6 — Evaluation and Hardening

## Goal
Turn a working prototype into a reliable submission.

## Automated
- unit tests;
- integration tests;
- smoke test;
- fusion boundary tests;
- fixture regressions.

## Manual
- phone browser;
- desktop;
- fresh session;
- network failure;
- Textract failure;
- image too large;
- bad image;
- unsupported product.

## Measure
- end-to-end latency;
- failure rate;
- feature values across fixtures;
- false suspicious on benign hard captures.

## Observability
Add structured logs and a small runbook.

## Rehearsal
Reset + run three scenarios 5 times.

Fix any flake before adding P1.

## Acceptance
No scenario depends on manual database edits during recording.

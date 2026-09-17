# Phase 2 — Identity Registry and Extraction

## Goal
Resolve product/batch/unit identity from real input.

## Tasks
1. Implement registry/reference tables.
2. Seed 2–3 products.
3. Seed valid batches and unit serials.
4. Add QR parser.
5. Add Textract adapter.
6. Normalize dates/batch/manufacturer.
7. Cross-check QR vs OCR-visible data.
8. Return verification level.
9. Add status: active/expired/recalled/revoked.
10. Add fixtures/tests.

## Rules
- QR parse success does not equal authenticity.
- Unknown serial cannot be changed to valid by LLM inference.
- If only batch is available, label assurance `BATCH`.
- Expiry is product status, not counterfeit verdict.

## Tests
- valid unit;
- valid batch-only;
- unknown unit;
- unknown batch;
- QR/OCR conflict;
- expired;
- revoked.

## Acceptance
Deployed scan returns real identity fields from seeded data.

# Phase 1 — Deployed Vertical Slice

## Goal
A phone uploads a medicine image to real AWS and receives a persisted placeholder analysis result.

## Tasks
1. Create private S3 scan bucket.
2. Create scan-events DynamoDB table.
3. `POST /uploads` returns presigned PUT.
4. Web uploads directly to S3.
5. `POST /scans/{id}/analyze` verifies object exists and persists event.
6. `GET /scans/{id}`.
7. Deploy API.
8. Deploy web to Amplify.
9. Add CloudWatch structured logs.
10. Create smoke-test script.
11. Record public URL/API in `MEMORY.md`.

## Placeholder response
May use fixed dimension values only in this phase, clearly marked internally `pipeline=placeholder`.

Remove placeholder before Phase 4 gate.

## Acceptance
Run the smoke test against deployed URL five times.

## Failure handling
If S3 CORS fails, fix origin rules.
If API binary upload is attempted, stop and restore direct-to-S3 design.

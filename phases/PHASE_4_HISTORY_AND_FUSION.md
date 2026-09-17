# Phase 4 — History Anomalies and Fusion

## Goal
Deliver the distinctive SCADS behavior.

## History
Query scan events by serial.

Implement:

### Serial reuse
Find prior events for same serial.

### Impossible travel
Use coarse/demo centroid mapping.

Example fixture:
- prior: Delhi demo at `T-60m`;
- current: Bengaluru demo;
- same serial.

Generate `IMPOSSIBLE_TRAVEL`.

### Post-sale reuse
If seeded unit state says dispensed/decommissioned and current event conflicts, generate finding.

## Fusion
Implement pure function:
`decide(evidence) -> DecisionResult`.

Inputs:
- quality;
- identity;
- physical;
- history;
- product status;
- reason findings.

Use geometric base + hard caps.

## Tests
- I=.99 P=.99 H=.1 + impossible travel => suspicious;
- low quality => unverifiable before fusion;
- expired otherwise clean => low authenticity risk + expired product warning;
- missing history explicitly lowers assurance or uses documented policy;
- same inputs deterministic.

## Demo seed/reset
Create a script that can:
- clear demo events safely;
- seed clone event;
- print expected next scenario.

## Acceptance
All three demo scenarios pass deployed smoke tests.

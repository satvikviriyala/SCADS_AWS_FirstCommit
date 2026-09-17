# Multi-Year Roadmap

The hackathon is the wedge, not the ceiling.

## Stage 0 — Hackathon: evidence fusion
- batch/unit registry;
- visual reference comparison;
- scan events;
- duplicate/impossible-travel;
- reasoned fusion.

## Stage 1 — Manufacturer pilot
### Unit identity
- unit-level serials;
- signed QR/Digital Link payload;
- manufacturer key management;
- line-side commissioning.

### Better reference enrollment
- multiple captures per packaging variant;
- controlled ROI templates;
- print-process baselines;
- packaging revision management.

### Pharmacy workflow
- authenticated dispensing/decommission event;
- suspect quarantine flow;
- manufacturer escalation.

## Stage 2 — Physical-digital binding
This is where SCADS becomes much harder to clone.

Options:
- copy-detection patterns integrated with QR;
- natural paper/foil texture fingerprint;
- stochastic print-noise fingerprint;
- intentionally printed microtexture;
- PUF-like optical tag;
- tamper-evident seal fingerprint.

Goal:
`serial` should be bound to a physical object that is difficult to reproduce.

A plain signed QR prevents forgery of new identifiers, but does **not** prevent copying the signed QR. Physical fingerprint + scan history addresses cloning.

## Stage 3 — Supply-chain event fabric

Adopt EPCIS-compatible semantics.

Capture:
- commissioning;
- packing/aggregation;
- shipping;
- receiving;
- dispensing;
- decommission;
- recall;
- consumer verification.

Build entity graph:
- unit;
- case;
- batch;
- manufacturer;
- distributor;
- retailer;
- location;
- device/source class.

## Stage 4 — Streaming anomaly intelligence

Start with interpretable features:
- impossible movement;
- clone fan-out;
- scan bursts;
- lifecycle violations;
- region mismatch;
- abnormal route;
- new high-risk retailer cluster.

Then model:
- Isolation Forest;
- robust density estimates;
- temporal models;
- graph embeddings;
- GNNs only when event volume and labels justify them.

Avoid “GNN because graph”.

## Stage 5 — Network risk

Move from pack-level verdict to:
- pharmacy risk;
- distributor risk;
- route risk;
- batch risk;
- geographic cluster risk.

Use Bayesian/updating risk with source reliability.

Do not publicly accuse a business based on a black-box score without investigation workflow and evidence.

## Stage 6 — Feedback and adjudication

Integrate:
- manufacturer investigation;
- regulator seizure outcomes;
- lab confirmation;
- recall;
- complaints;
- adverse-event clusters.

These become high-value labels.

Retraining/evaluation must distinguish:
- fake packaging;
- diverted authentic;
- expired;
- substandard chemistry;
- data error.

## Stage 7 — Offline-first field mode

For low-connectivity areas:
- signed identifier verification offline;
- cached compact product/reference metadata;
- on-device quality/feature extraction where feasible;
- queue events;
- sync later;
- conflict-aware event ingestion.

## Stage 8 — Interoperability

Adapters:
- GS1 Digital Link;
- EPCIS 2.0;
- manufacturer ERP/MES;
- WMS;
- pharmacy software;
- regulator systems.

## Stage 9 — Higher-assurance verification

Partner integrations can add:
- spectroscopy;
- portable chemical assays;
- on-dose identifiers;
- temperature/cold-chain evidence.

SCADS then becomes the evidence-fusion layer, not merely the camera app.

## North-star architecture

```text
Cryptographic identity
        +
Physical fingerprint
        +
Supply-chain event history
        +
Behavioral/network anomaly
        +
Regulatory/lab feedback
        =
Continuously updated trust evidence
```

## Moats

The defensible long-term asset is not a QR scanner or a single CNN.

It is:
- manufacturer enrollment network;
- unit/event corpus;
- physical fingerprint baselines;
- adjudicated counterfeit labels;
- anomaly graph;
- regulator/manufacturer workflows;
- calibrated evidence fusion.

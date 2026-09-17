# Product Vision

## 1. Problem

Counterfeit and substandard medicines are not one failure mode.

A malicious pack can contain:
- a completely invented identity;
- a copied valid batch number;
- a copied valid unit serial;
- packaging close enough to fool a human;
- genuine packaging diverted and refilled;
- a legitimate product moved through an illegitimate route;
- a recalled/expired authentic product;
- a chemically substandard product whose packaging is perfectly authentic.

Therefore no phone-only packaging system can solve every pharmaceutical quality problem. SCADS focuses on a useful and scalable slice:

> **Detect contradictions between a medicine’s claimed digital identity, its physical packaging evidence, and its observed supply-chain/scan behavior.**

## 2. Why QR/database existence is insufficient

A database answer such as `serial exists` proves, at most, that an identifier was issued.

It does not prove:
- the identifier is on the original physical pack;
- the same identifier was not copied onto 1,000 counterfeit packs;
- the pack is in a plausible location/lifecycle state;
- the print is from the enrolled manufacturing process;
- the drug contents match the label.

SCADS turns verification from a boolean lookup into evidence fusion.

## 3. Evidence layers

### Layer A — Digital identity
Questions:
- Is the product known?
- Is the batch known?
- Is the unit serial known?
- Is the identifier revoked?
- Does QR data agree with OCR-visible packaging?
- Is it expired/recalled?

### Layer B — Physical packaging
Questions:
- Is the photo good enough to judge?
- Does the package align geometrically to the expected artwork?
- Are text anchors in the expected locations?
- Is the layout/structure consistent?
- Are print edges/sharpness characteristics plausible?
- Later: does a copy-sensitive/PUF-like fingerprint match enrollment?

### Layer C — Event/history context
Questions:
- Was this serial seen before?
- Was it already sold/consumed/decommissioned?
- Did it appear impossibly far away too quickly?
- Does the sequence of custody events make sense?
- Is there a burst pattern suggesting mass cloning?

### Layer D — Supply-chain network context
Future:
- Which distributor/retailer/route repeatedly emits anomalous units?
- Which batches cluster in adverse reports?
- Is a connected subgraph suddenly changing behavior?

### Layer E — Laboratory / chemical evidence
Out of scope for a phone-only MVP, but SCADS should allow higher-assurance systems to plug in later:
- spectroscopy;
- lab assays;
- manufacturer QA;
- regulator seizure results.

## 4. Users

### Consumer
Wants a simple scan and a safe interpretation.

### Pharmacist
Needs a fast check before dispensing and a way to escalate suspicious packs.

### Distributor / manufacturer
Needs anomaly clusters, clone signals and route integrity.

### Regulator / investigator
Needs evidence-rich alerts, provenance, repeatability, and audit trails.

Hackathon UI should optimize primarily for the consumer/pharmacist scan while showing that the event data enables enterprise/regulatory workflows.

## 5. Decision language

Do not conflate authenticity with safety.

### `LOW_OBSERVED_RISK`
No configured contradiction was observed and available evidence is consistent.

### `REVIEW_REQUIRED`
Evidence is mixed or marginal.

### `SUSPICIOUS`
One or more strong contradictions or severe risk findings exist.

### `UNABLE_TO_VERIFY`
The system lacks adequate evidence, e.g. poor image, unsupported product, missing reference or extraction failure.

## 6. Hackathon wedge

The weekend product needs only enough breadth to prove the architecture:

- 2–3 enrolled medicine packages;
- valid registry records;
- physical comparison;
- one scan-history anomaly;
- a clear fusion engine;
- excellent explanation;
- reliable AWS deployment.

This is better than a nominally huge platform where none of the advanced layers actually work.

## 7. Product differentiator

The memorable statement is:

> **QR asks “was this identifier issued?” SCADS asks “does this physical pack with this identity make sense right now?”**

Long term:

> **SCADS becomes a trust fabric over medicine units, physical fingerprints and supply-chain events.**

## 8. Non-goals for the hackathon

- diagnosis or treatment advice;
- chemical authenticity certification;
- replacing CDSCO/regulatory investigation;
- nationwide manufacturer integration;
- blockchain for its own sake;
- training a giant vision model;
- graph neural networks with synthetic claims of production accuracy;
- collecting precise user location by default.

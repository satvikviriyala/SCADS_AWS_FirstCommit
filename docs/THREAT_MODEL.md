# Threat Model

## 1. Assets

- trustworthy registry data;
- reference images/fingerprints;
- serial lifecycle status;
- scan-event history;
- decision integrity;
- user privacy;
- manufacturer/regulator credentials;
- public service availability.

## 2. Adversaries

### A. Casual counterfeiter
Copies batch/QR and approximate packaging.

### B. Sophisticated printer
Produces high-quality visual clone.

### C. Serial cloner
Copies one real unit identity across many packs.

### D. Supply-chain insider
Has access to legitimate packaging/identifiers and diverts goods.

### E. API abuser
Attempts enumeration, poisoning, DoS, oversized uploads.

### F. Malicious/curious user
Uploads arbitrary images, manipulates metadata/location.

### G. Compromised admin/manufacturer credential
Attempts registry/reference corruption.

## 3. Threats and mitigations

| Threat | Why basic QR fails | SCADS mitigation |
|---|---|---|
| copied batch | batch exists | unit serial + physical evidence + history |
| copied serial | serial exists | duplicate/geographic/lifecycle anomalies |
| guessed valid-looking id | syntax plausible | registry lookup / signed payload later |
| high-quality print clone | image classifier may pass | event history + future fingerprint |
| low-quality genuine photo | visual model may falsely reject | quality gate -> unverifiable |
| screenshot/replayed image | image looks genuine | scan history; future challenge capture |
| stolen genuine package | visual + id can pass | lifecycle/custody anomalies; cannot fully solve content replacement |
| registry poisoning | every check can be subverted | authenticated enrollment, least privilege, audit |
| scan-history poisoning | false anomaly creation | rate limits, confidence on event sources, authenticated supply-chain events |
| location spoof | impossible-travel false alert | location is supporting evidence, source-confidence model |
| prompt injection in package text | multimodal LLM may follow text | Bedrock never controls core verdict; structured prompt isolation |
| oversized file | resource exhaustion | size/type/dimension limits |
| enumeration | discover valid serials | generic public error wording, rate limits, no bulk query |
| secret leakage | system compromise | Secrets Manager/env, never repo |

## 4. Important unsolved threats

### Perfect clone with copied identity before first legitimate scan
History may not yet expose it. Physical fingerprint/signature enrollment improves this later.

### Genuine packaging refilled with fake medicine
Packaging-only evidence can fail entirely. Requires tamper evidence, custody data, chemical testing, or on-dose authentication.

### Compromised manufacturer source
If enrollment source is malicious, SCADS can certify bad ground truth. Production needs governance and regulator/manufacturer trust anchors.

### Chemical degradation/substandard content
Cannot be inferred reliably from package image.

These limitations should be stated, not hidden.

## 5. Reference enrollment security

Reference enrollment is more sensitive than consumer scanning.

Production requirements:
- manufacturer/admin authentication;
- maker-checker for critical changes;
- signed/versioned reference profile;
- immutable audit;
- rollback;
- separation of duties.

Hackathon:
- seed via controlled script;
- no public enrollment endpoint.

## 6. Event-source confidence

Not all scans are equal.

Future event confidence tiers:
1. manufacturer-line event;
2. authenticated distributor/pharmacy;
3. consumer scan;
4. anonymous scan.

Graph/anomaly models should weight source trust.

## 7. Prompt injection defense

If package text is sent to an LLM:
- treat OCR text as untrusted data;
- use explicit JSON schema;
- never allow package text to override system instructions;
- never ask the LLM to decide authenticity;
- validate output against enum/schema;
- fallback deterministically.

## 8. Abuse-resistant decisions

Do not expose precise internal thresholds in the consumer response in production. For hackathon, source code can be public as required, but architecture should anticipate adversarial adaptation.

## 9. Privacy threat

Location is useful for clones but dangerous if over-collected.

Default:
- `NONE`.

Hackathon:
- synthetic named locations for demo.

Production:
- explicit consent;
- coarse cells;
- short retention;
- aggregate analytics;
- never tie to personal identity unless legally required and justified.

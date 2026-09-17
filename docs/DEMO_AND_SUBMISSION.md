# Demo and Submission Plan

## 1. Hackathon facts that affect strategy

First Commit runs Sept 17–20, 2026. The Ship It first prize is for a project deployed live on AWS with a URL. Judging explicitly considers idea/impact, AWS usage, learning, execution and the <=3 minute demo. Judges see the submitted artifact/video, not a live pitch.

Therefore:
- reliability beats hidden breadth;
- the video must show the differentiator;
- AWS must be visible in the actual implementation;
- submit early, then improve before deadline.

Verify current deadline/form on event page before final submission.

## 2. Three-minute video

### 0:00–0:20 — Problem
Show a medicine pack.

Script concept:
“Most consumer verification asks whether a QR or batch number exists. A counterfeiter can copy a real identifier. The harder question is whether this physical pack with this identity makes sense right now.”

Avoid unsourced death statistics.

### 0:20–0:35 — SCADS concept
One diagram:
- identity;
- physical packaging;
- history.

“Independent evidence. Contradictions cannot average away.”

### 0:35–1:05 — Demo 1: genuine fixture
Scan.
Show:
- identity valid;
- package match;
- history clean;
- low observed risk.

Emphasize disclaimer: packaging checks do not assay chemical contents.

### 1:05–1:35 — Demo 2: visual tamper
Use synthetic tampered version with same valid identity.
Show physical feature drop and reason.

### 1:35–2:05 — Demo 3: cloned serial
Use visually excellent image.
Registry says serial valid.
History says same serial was seen far away recently / already used.
Result becomes suspicious.

This is the memorable moment.

### 2:05–2:30 — AWS architecture
Show compact architecture:
Amplify → API Gateway → Lambda → S3/Textract/DynamoDB → CV/fusion → result.
Mention Bedrock only if actually used.

Explain serverless/cost decision.

### 2:30–2:50 — Future
One sentence per layer:
- unit serialization;
- factory physical fingerprint;
- EPCIS supply-chain events;
- graph anomalies.

Do not demo imaginary features.

### 2:50–3:00 — Close
“QR verifies an identifier. SCADS verifies whether identity, package and history agree.”

## 3. UI result card

Top:
- decision badge.

Then three evidence cards:
- Identity
- Physical package
- Scan history

Then:
- reason codes translated;
- safe next action;
- “What this scan cannot prove.”

Keep score breakdown visually simple.

## 4. Submission writeup

Structure:

### Problem
Counterfeit medicine verification needs more than identifier existence.

### Existing approaches
Serialization/QR and image inspection both help but each has failure modes.

### What we built
Multi-evidence phone scan with contradiction-aware fusion.

### Architecture
Actual AWS path.

### What we learned
Mention real engineering discoveries:
- image registration matters before SSIM;
- poor scan must be treated as uncertainty;
- direct-to-S3 upload;
- deterministic verdict vs generative explanation.

### Limitations
Packaging cannot prove chemistry; synthetic tamper data is not a real counterfeit benchmark.

### Future
Physical fingerprint + serialized event graph.

## 5. README proof checklist

- working URL;
- 30-second GIF/screenshot if allowed;
- architecture diagram;
- local run;
- deploy;
- sample scenarios;
- limitations;
- AWS services;
- AI coding tools disclosed as required;
- attributions/licenses.

## 6. Judge-focused checklist

### Idea and impact
- real healthcare problem;
- precise scope;
- avoids vague “AI solves counterfeits”.

### AWS
- live;
- architecture intentional;
- serverless cost discussion.

### Learning
- real challenges, not generic “learned AWS”.

### Execution
- all three scenarios work repeatedly.

### Demo
- no dead time;
- no terminal debugging;
- visible feature behavior.

## 7. Before recording

Freeze a stable commit.

Run:
- seed/reset;
- smoke test;
- all tests;
- mobile flow;
- exact three scenarios.

Then record.

Do not deploy an untested architectural refactor after recording unless necessary.

## 8. Claims not to make

Avoid:
- “first ever”;
- “unprecedented”;
- “detects all counterfeit medicines”;
- “90% accurate” without your own supported evaluation;
- “prevents deaths” as quantified outcome;
- “blockchain is required”;
- “AI proves medicine is genuine”.

## 9. Prize optimization without gimmicks

The best route to the first prize is:
- solve a concrete problem;
- demonstrate a non-obvious failure of existing simplistic verification;
- show a working AWS system;
- make the third clone scenario memorable;
- show disciplined limitations;
- have an unusually polished three-minute narrative.

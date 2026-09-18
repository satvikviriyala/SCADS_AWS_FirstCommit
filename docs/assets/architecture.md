# SCADS architecture diagrams

Source for the diagrams in `README.md`. Rendered by GitHub automatically.

## Request path

```mermaid
flowchart LR
    subgraph Phone["Phone / PWA"]
        UI[Mobile web client<br/>downscale, strip EXIF,<br/>decode QR]
    end

    subgraph AWS["AWS"]
        AMP[Amplify Hosting<br/>static client]
        API[API Gateway<br/>HTTP API + throttling]
        L[Lambda<br/>scads-api]
        S3S[(S3 scans<br/>private, 7-day lifecycle)]
        S3R[(S3 references<br/>private, versioned)]
        TX[Textract<br/>DetectDocumentText]
        DDB1[(DynamoDB<br/>registry)]
        DDB2[(DynamoDB<br/>scan events<br/>+ serial-time GSI)]
        DDB3[(DynamoDB<br/>reference profiles)]
        BR[Bedrock<br/>optional wording]
        CW[CloudWatch<br/>logs, metrics, alarms]
    end

    AMP -->|serves| UI
    UI -->|1 request upload target| API
    API --> L
    L -->|presigned PUT| S3S
    UI -->|2 direct upload| S3S
    UI -->|3 analyze| API

    L -->|read image| S3S
    L -->|OCR| TX
    L -->|resolve identity| DDB1
    L -->|reference profile| DDB3
    L -->|reference artwork| S3R
    L -->|prior scans by serial| DDB2
    L -->|append scan event| DDB2
    L -.->|codes only, never pack text| BR
    L --> CW
    L -->|result| API --> UI
```

## Evidence pipeline inside the Lambda

```mermaid
flowchart TB
    IN[Uploaded image] --> V[Validate<br/>magic bytes, size, dimensions]
    V --> Q{Scan quality gate<br/>sharpness, exposure, resolution}

    Q -->|below floor| U[UNABLE_TO_VERIFY<br/>with retake advice]

    Q -->|adequate| ID[Identity<br/>QR then OCR<br/>registry lookup<br/>QR vs print cross-check]
    Q -->|adequate| PH[Physical<br/>locate pack, rectify,<br/>compare regions]
    ID --> HI[History<br/>reuse, impossible travel,<br/>post-sale, burst]

    ID --> F[Decision engine]
    PH --> F
    HI --> F
    PS[Product status<br/>expiry, recall] --> F

    F --> G1[Weighted geometric fusion<br/>over available dimensions]
    G1 --> G2[Hard score caps]
    G2 --> G3[Decision-class ceilings]
    G3 --> OUT[Decision + reason codes<br/>+ versions]

    U --> OUT
```

## Why the three dimensions cannot be averaged

```mermaid
flowchart LR
    subgraph Clone["Demo scenario C: a cloned serial"]
        I[Identity 0.96<br/>the serial really was issued]
        P[Physical 0.87<br/>the pack really is well printed]
        H[History 0.10<br/>seen 1,740 km away, 58 min ago]
    end

    I --> A["Weighted average<br/>0.709<br/>history can move this<br/>by at most its weight, 25%"]
    P --> A
    H --> A
    A --> AR[REVIEW_REQUIRED<br/>understates it]

    I --> G["Weighted geometric mean<br/>0.524<br/>a near-zero input scales<br/>the whole product"]
    P --> G
    H --> G
    G --> C[Cap: IMPOSSIBLE_TRAVEL<br/>max 0.25]
    C --> GR[SUSPICIOUS<br/>correct]
```

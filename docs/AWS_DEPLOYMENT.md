# AWS Deployment Plan

## 1. Region

Choose one region that supports:
- Lambda;
- API Gateway;
- S3;
- DynamoDB;
- Textract;
- Amplify;
- selected Bedrock model if Bedrock is used.

Record the actual region in `MEMORY.md`.

Avoid cross-region calls in the MVP.

## 2. Services

### Amplify Hosting
Hosts mobile-first web app.

### API Gateway HTTP API
Public API surface.

### Lambda
- API/orchestrator
- optional CV container function
- seed/admin functions only if necessary

### S3
Buckets/prefixes:
- raw scans
- references

Never public.

### Textract
OCR and bounding boxes.

### DynamoDB
- registry
- scan events
- reference metadata
- optional alerts

### Bedrock [optional]
Human-readable explanation / normalization.

### CloudWatch
Logs, metrics and alarms.

### Cognito [P1]
Admin/manufacturer authentication only.

### EventBridge/SQS/Step Functions [only if required]
Async pipeline or future events.

---

## 3. IaC

Prefer SAM for speed unless team already works faster with CDK.

Target resources:

```text
AWS::S3::Bucket ScanBucket
AWS::S3::Bucket ReferenceBucket
AWS::DynamoDB::Table RegistryTable
AWS::DynamoDB::Table ScanEventsTable
AWS::DynamoDB::Table ReferenceTable
AWS::Serverless::Function ApiFunction
AWS::Serverless::Function CvFunction
AWS::Serverless::HttpApi Api
```

Outputs:
- API URL;
- bucket name only if safe for client config;
- table names;
- region.

## 4. IAM

### API Lambda
Allow only:
- presign put for scan prefix;
- read scan objects;
- read registry/reference metadata;
- read/write scan events;
- invoke Textract;
- invoke CV function;
- optional Bedrock invoke model.

### CV Lambda
Allow:
- read scan object;
- read reference object;
- no registry mutation.

### Frontend
No AWS credentials.
Uses pre-signed upload and public API.

Least privilege is part of architecture quality.

---

## 5. S3

Settings:
- block public access;
- SSE-S3 or SSE-KMS if practical;
- CORS only for deployed frontend origin;
- lifecycle for demo scan images;
- random object names.

Presigned constraints:
- short expiry;
- expected content type;
- max size enforced additionally at backend/runtime.

## 6. DynamoDB

Hackathon:
- on-demand capacity;
- PITR optional if it adds no friction;
- TTL for disposable demo events only if desired.

Indexes defined in `docs/DATA_MODEL.md`.

## 7. Lambda configuration

Environment:

```text
SCADS_ENV
REGISTRY_TABLE
SCAN_EVENTS_TABLE
REFERENCE_TABLE
SCAN_BUCKET
REFERENCE_BUCKET
FUSION_POLICY_VERSION
CV_PIPELINE_VERSION
BEDROCK_ENABLED
```

Do not place secrets in repository.

### CV packaging
If native dependencies:
- container image with pinned versions;
- architecture matching Lambda runtime;
- local smoke test using SAM if possible.

## 8. Observability

Structured JSON logs:

```json
{
  "event": "scan.completed",
  "scan_id": "...",
  "decision": "SUSPICIOUS",
  "latency_ms": 3120,
  "reason_codes": ["IMPOSSIBLE_TRAVEL"],
  "pipeline_version": "cv_0.1.0"
}
```

Do not log:
- presigned URLs;
- tokens;
- raw OCR unnecessarily;
- exact private location.

Metrics:
- scans count;
- success/failure;
- latency;
- unverifiable rate;
- dependency error count.

## 9. Deployment workflow

Example SAM path:

```bash
sam validate
sam build
sam deploy --guided   # first time
sam deploy            # later
```

Frontend:
```bash
npm ci
npm test
npm run build
# connected Amplify deployment
```

Exact commands must be updated in `MEMORY.md`.

## 10. Smoke test

A script should:
1. call `/health`;
2. request upload;
3. upload fixture;
4. start analysis;
5. poll if needed;
6. assert expected decision/reason code.

Run after every deploy.

## 11. Rollback

- retain prior deploy artifact;
- Git-tag stable demo commit;
- do not push architecture changes directly before recording demo;
- if optional Bedrock breaks, switch `BEDROCK_ENABLED=false`;
- if history query breaks, do not silently return H=1; return dependency failure or configured degraded state.

## 12. Cost

The hackathon page explicitly scores architecture/cost decisions in Ship It.

Explain:
- serverless request path;
- direct-to-S3 uploads;
- DynamoDB on-demand;
- no always-on GPU;
- optional model calls;
- lifecycle cleanup;
- bounded image sizes.

## 13. Demo proof

The video should visibly demonstrate:
- public Amplify URL;
- scan UX;
- result;
- one quick architecture visual naming actual AWS services.

Do not spend video time scrolling the AWS console unless it proves something essential.

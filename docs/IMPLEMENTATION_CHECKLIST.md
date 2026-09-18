# Implementation Checklist

> Updated after the P0 build. Items still open require AWS credentials or a
> recording, neither of which exists in the development environment.

## P0
- [x] repo skeleton
- [x] health endpoint
- [x] IaC validates
- [ ] Amplify deployed *(script ready: `scripts/deploy_web.py`; needs credentials)*
- [ ] API Gateway deployed *(script ready: `scripts/deploy.py`; needs credentials)*
- [x] private S3 upload
- [x] DynamoDB scan persistence
- [x] QR parser
- [x] Textract adapter
- [x] registry seed
- [x] identity evaluator
- [x] quality gate
- [x] registration
- [x] OCR layout feature
- [x] SSIM feature
- [x] print/edge feature
- [x] physical score
- [x] serial event query
- [x] serial reuse rule
- [x] impossible travel rule
- [x] fusion engine
- [x] reason codes
- [x] safe result wording
- [x] demo reset/seed
- [x] clean fixture
- [x] visual-tamper fixture
- [x] cloned-serial fixture
- [x] unit tests
- [x] deployed smoke test
- [x] structured logs
- [x] mobile UX
- [ ] public URL checked *(blocked on deployment)*
- [x] README complete
- [x] secret scan
- [x] attribution/license audit
- [ ] <=3 minute demo recorded *(script in docs/DEMO_AND_SUBMISSION.md)*
- [ ] submission created early *(blocked on deployment)*

## P1
- [x] Bedrock explanation *(implemented with output validation; disabled by default, `--bedrock` to enable)*
- [ ] tamper slider
- [ ] mismatch overlay
- [x] history timeline
- [ ] Cognito admin
- [x] rate limiting *(API Gateway throttling in the template)* / [ ] WAF
- [x] multiple genuine captures *(`genuine_alternate_angle`, `genuine_hard_capture`)*
- [ ] latency dashboard *(p95 CloudWatch alarm exists; no dashboard)*

## Added beyond the original checklist

- [x] measurement harness behind every threshold (`scripts/calibrate.py`)
- [x] infrastructure security assertions (`tests/unit/test_infra.py`)
- [x] static web-client checks, since there is no JS runtime here
- [x] Lambda packaging without Docker, with an excluded-import guard
- [x] deployment without the AWS CLI or SAM CLI (boto3 + CloudFormation)
- [x] demo repeatability: tagged demo traffic + scoped reset, verified over
      five rehearsals

# Security and Privacy

## 1. Data minimization

Consumer verification should work without account creation.

Do not collect:
- name;
- phone;
- Aadhaar;
- medical condition;
- prescription;
- precise location by default.

## 2. Location

For the hackathon, anomaly location should preferably be **synthetic demo context**, e.g. Bengaluru vs Delhi.

If browser location is ever used:
- ask explicit permission;
- bucket/coarsen immediately;
- do not persist exact coordinates;
- show why it is used;
- allow verification without it.

## 3. Upload safety

- JPEG/PNG allowlist;
- validate magic bytes;
- image decode in constrained library;
- max bytes;
- max pixel dimensions;
- random keys;
- no user-controlled path traversal;
- strip/ignore EXIF;
- private S3.

## 4. API

- schema validation;
- bounded strings;
- no raw database query exposure;
- throttling;
- CORS restricted to expected origins in production;
- safe generic errors;
- correlation id.

## 5. Admin plane

Registry/reference changes require authentication.

For hackathon, use scripts with developer AWS credentials rather than expose an admin web page unless time permits.

If admin UI exists:
- Cognito;
- separate route;
- role check;
- audit.

## 6. Secrets

- `.env.example`, never `.env`;
- GitHub secret scan before submission;
- use IAM roles rather than static AWS keys in deployed services;
- Bedrock requires role permissions, not embedded key.

## 7. Data integrity

Every result captures:
- pipeline version;
- fusion policy;
- reference version;
- source evidence identifiers.

Future:
- sign enrollment artifacts;
- append-only event log;
- integrity hashes.

## 8. User messaging

Never create panic.

Suspicious result:
> “This scan found contradictions that need review. Do not rely on this scan alone. If you have concerns, avoid using the pack until it is checked by a pharmacist, manufacturer, or appropriate authority.”

Unverifiable:
> “The scan did not contain enough reliable evidence. Retake the image in good light or use another verification route.”

Low observed risk:
> “The available identity, packaging and scan-history checks were consistent. This does not test the medicine’s chemical contents.”

## 9. Retention

Raw photos should not live forever merely because storage is cheap.

Hackathon:
- short S3 lifecycle acceptable;
- retain seeded references.

Production:
- documented retention by evidence purpose;
- investigation hold mechanism;
- privacy deletion process where legally applicable.

## 10. Model privacy

If using Bedrock:
- send only data necessary for explanation/normalization;
- avoid raw personal data;
- do not send secrets;
- validate output.

Core verdict works with Bedrock disabled.

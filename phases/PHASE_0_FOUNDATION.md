# Phase 0 — Foundation

## Goal
Create a boring, testable base that can deploy.

## Tasks
1. Initialize frontend and backend.
2. Create shared API/reason-code schemas.
3. Add formatter/linter/typecheck.
4. Add Python test setup for detection engine.
5. Add `.gitignore`, `.env.example`.
6. Add IaC skeleton.
7. Add CI if quick.
8. Add health endpoint.
9. Add placeholder mobile page.
10. Update `MEMORY.md`.

## Stack [as built]
- web: plain HTML + CSS + ES modules, no build step (there is no Node toolchain
  in this environment, and Amplify Hosting serves static assets directly);
- backend: Python Lambda, single language across API, CV and decision;
- CV/decision: Python with numpy + Pillow only;
- IaC: SAM template, deployed through boto3 + CloudFormation.

One language boundary, not three.

## Acceptance [met]
- `python -m pytest tests/ -q` passes;
- `/health` answers locally via `scripts/dev_server.py`, reporting which
  backends are live;
- the CloudFormation template parses and its security properties are asserted
  by `tests/unit/test_infra.py` (there is no SAM CLI here, and `sam validate`
  would not check those properties anyway);
- the web client is checked statically by `tests/unit/test_web_client.py`,
  since there is no JS runtime to execute it;
- `python scripts/secret_scan.py` is clean;
- README gives bootstrap commands.

## Do not
- train a model;
- build admin dashboard;
- design a GNN;
- add blockchain.

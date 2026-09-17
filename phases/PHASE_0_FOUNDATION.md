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

## Suggested stack
- web: React + TypeScript;
- backend: Python 3.12 Lambda/FastAPI-style handler or Node orchestrator + Python CV function;
- CV/decision: Python;
- IaC: SAM.

Prefer fewer language boundaries if team is faster in one language.

## Acceptance
- `npm run build` succeeds;
- backend unit test succeeds;
- `/health` works locally;
- IaC validates;
- no secret in git;
- README gives bootstrap commands.

## Do not
- train a model;
- build admin dashboard;
- design a GNN;
- add blockchain.

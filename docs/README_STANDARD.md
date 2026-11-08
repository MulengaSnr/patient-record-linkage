# Portfolio documentation standard

Every repo in this portfolio follows these rules so a recruiter can judge any project in two minutes and an engineer can run it in ten.

## The two-minute test
A reader who sees only the top screen of the README must learn: **what problem**, **what data**, **what result vs. baseline**, **what stack**, and **status**. That is what the "At a glance" table is for.

## Honesty rules (non-negotiable)
1. Every metric in the README is reproduced by a command in the repo, on a held-out test set, and shown next to a baseline.
2. "Deployed" only with a working link. "Production-style" means the engineering practices are present, not that real users depend on it.
3. No real patient, client or employer data. Public, synthetic or licensed only, with the licence recorded in `data/README.md`.
4. Limitations section is mandatory and specific.
5. Business impact is stated as *potential* ("could reduce…") unless measured.

## Writing style
- Plain English first, technical detail second. Explain *why* each choice was made.
- Short sections, tables over paragraphs, one figure per key finding.
- UK spelling (visualisation, organisation, licence as a noun).

## Required files
| File | Purpose |
|---|---|
| `README.md` | From the template, sections deleted if not applicable |
| `LICENSE` | MIT for code; data keeps its own licence |
| `data/README.md` | Provenance and licence table |
| `docs/MODEL_CARD.md` | Any repo with a predictive model |
| `reports/findings.md` | Stakeholder-facing summary |
| `.env.example` | If any credentials are needed |
| `.github/workflows/ci.yml` | Lint + tests on every push |

## Repository naming convention
- Lowercase, hyphenated, **domain first, method second**: `readmission-risk-model`, `patient-record-linkage`, `uk-public-docs-rag`.
- No `project1`, `assignment`, `final`, `test`, `my-`.
- GitHub description: one sentence with the problem + key technologies, e.g.
  *"Predicting 30-day hospital readmission with calibrated gradient boosting, SHAP and fairness audit (Python, scikit-learn, XGBoost)."*
- Topics (tags): 4–8 of `python`, `machine-learning`, `healthcare`, `mlops`, `data-engineering`, `airflow`, `azure`, `fastapi`, `rag`, `llm`, …

## Git workflow
- `main` is always green (CI passing).
- Work on short branches: `feat/…`, `fix/…`, `docs/…`; merge via pull request using the PR template, even when working alone (the PR description is evidence of review practice).
- Commit messages: imperative, specific: `Add stratified CV and calibration curve`, not `update`.
- Track work as GitHub Issues using the Task template.

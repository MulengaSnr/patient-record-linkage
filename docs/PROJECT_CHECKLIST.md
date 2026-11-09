# Project checklist

Status of this project, last reviewed 9 November 2026. An unticked item says why.

## Plan
- [x] Business problem and decision-maker written down
- [x] Technical objectives and success metric (with baseline) defined
- [x] Dataset chosen; licence checked and recorded in `data/README.md`
- [x] Architecture sketched in README
- [ ] Issues created for each major task: not done. Work was tracked as one pull request per step (PRs #1 to #10)

## Build
- [x] Reproducible data download / generation script
- [x] Data validation checks
- [ ] EDA notebook with key findings: not done. Data profiling is in the quality checks, `reports/findings.md` and the dashboard
- [x] Train / validation / test split decided **before** modelling; leakage reviewed
- [x] Baseline model
- [ ] Candidate models + cross-validation: not applicable. One unsupervised model is compared with the rule baseline, and the threshold was chosen on a separate population
- [x] Final evaluation on test set (once)
- [x] Explainability + fairness analysis
- [x] Unit tests for `src/` logic; CI green

## Document
- [x] README complete (two-minute test passes)
- [x] Model card (if a model)
- [x] `reports/findings.md` for a non-technical reader
- [x] Screenshot / headline figure
- [x] Limitations and next steps

## Publish (only after approval)
- [x] No secrets (`git log -p | grep -i key` reviewed), no real personal data
- [ ] Repo description + topics set: awaiting approval to publish
- [ ] Linked from profile README and landing page: awaiting approval to publish

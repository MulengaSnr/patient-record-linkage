# Project checklist

Copy into each new repo and tick off as work progresses.

## Plan
- [ ] Business problem and decision-maker written down
- [ ] Technical objectives and success metric (with baseline) defined
- [ ] Dataset chosen; licence checked and recorded in `data/README.md`
- [ ] Architecture sketched in README
- [ ] Issues created for each major task

## Build
- [ ] Reproducible data download / generation script
- [ ] Data validation checks
- [ ] EDA notebook with key findings
- [ ] Train / validation / test split decided **before** modelling; leakage reviewed
- [ ] Baseline model
- [ ] Candidate models + cross-validation
- [ ] Final evaluation on test set (once)
- [ ] Explainability + fairness analysis
- [ ] Unit tests for `src/` logic; CI green

## Document
- [ ] README complete (two-minute test passes)
- [ ] Model card (if a model)
- [ ] `reports/findings.md` for a non-technical reader
- [ ] Screenshot / headline figure
- [ ] Limitations and next steps

## Publish (only after approval)
- [ ] No secrets (`git log -p | grep -i key` reviewed), no real personal data
- [ ] Repo description + topics set
- [ ] Linked from profile README and landing page

# Model card: Splink patient record linkage

_Based on Mitchell et al. (2019), "Model Cards for Model Reporting"._

## Model details
- **Type:** Fellegi-Sunter probabilistic record linkage, using Splink 5.0.0 on DuckDB. It deduplicates records across three simulated source systems, then clusters pairs into people.
- **Comparisons:** first name and surname, date of birth, sex, NHS number, postcode and address.
- **Version:** configuration in `configs/default.yaml`. Results were produced from commit `77e23e1`.
- **Owner:** Enock Mulenga
- **Date:** 2026-11-08

## Intended use
- **Primary use:** a portfolio demonstration of a linkage pipeline and how to evaluate one.
- **Out of scope:** any real patient data or clinical decision. Using it on real data would need new parameter estimates, new thresholds, a re-run of the fairness analysis and appropriate governance.

## Training and evaluation data
All data is synthetic: Synthea patients copied into hospital, GP and laboratory sources, with errors injected at three illustrative levels (`configs/default.yaml`).

| Population | Seed | People | Records (low / medium / high) | Use |
|---|---:|---:|---|---|
| train | 101 | 11,463 | 24,316 / 24,929 / 26,586 | Estimate parameters, without labels |
| tune | 202 | 11,407 | 24,074 / 24,818 / 26,627 | Choose the threshold |
| test | 303 | 11,597 | 24,563 / 25,205 / 26,874 | Final results, used once |

A separate model is trained for each error level, on the matching level of `train`. Known biases: names and addresses are American, about a quarter of people have no usable postcode, and only women have a maiden name.

## Metrics
False merges are treated as the more serious error, so the rule, set before any linkage was run, is the lowest swept threshold reaching 99.5% pairwise precision on `tune`. That gave a match probability of **0.99** at all three levels (tune precision 99.87%, 99.95% and 99.64%). Probabilities are not assessed for calibration, and the threshold sweep is coarse: 0.5, 0.7, 0.8, 0.9, 0.95, 0.99, 0.999 and 0.9999.

Test results at that threshold, against deterministic rules (exact NHS number, or exact first name, surname and date of birth):

| Metric | Low: Splink | Low: baseline | Medium: Splink | Medium: baseline | High: Splink | High: baseline |
|---|---:|---:|---:|---:|---:|---:|
| Pairwise precision | 99.94% | 99.81% | 99.90% | 99.22% | 99.92% | 97.64% |
| Pairwise recall | 98.69% | 94.81% | 96.34% | 85.81% | 89.15% | 70.95% |
| Pairwise F1 | 99.31% | 97.25% | 98.09% | 92.03% | 94.23% | 82.18% |
| People split (of those with several records) | 1.67% | 6.40% | 4.73% | 17.61% | 14.52% | 36.25% |
| People falsely merged (of all people) | 0.07% | 0.09% | 0.05% | 0.57% | 0.07% | 1.83% |

**Share of records still linked to their person at the high level: records with no error, and the 13 injected errors with the lowest rates:**

| Injected error | Records | Linked |
|---|---:|---:|
| None | 6,891 | 97.6% |
| Date of birth missing | 756 | 57.4% |
| Date of birth typo | 744 | 58.2% |
| Day and month swapped | 218 | 60.6% |
| Names swapped | 365 | 62.2% |
| First name reduced to initial | 711 | 64.4% |
| Sex wrong | 249 | 72.3% |
| Wrong person's NHS number | 179 | 81.6% |
| First name nickname | 1,244 | 82.2% |
| First name typo | 1,887 | 84.1% |
| NHS number digit typo | 794 | 86.0% |
| Surname typo | 1,941 | 88.2% |
| Moved address | 6,235 | 88.7% |
| Maiden name used | 1,954 | 88.9% |

## Subgroup performance (fairness)
Share of people with several records who were split, on the test population:

| Group | People | Low | Medium | High |
|---|---:|---:|---:|---:|
| **Overall** | 11,597 | 1.67% | 4.73% | 14.52% |
| Female | 5,689 | 1.99% | 5.70% | 15.51% |
| Male | 5,908 | 1.35% | 3.80% | 13.56% |
| Under 18 | 2,080 | 1.85% | 4.74% | 13.06% |
| 18–39 | 3,041 | 1.65% | 4.48% | 15.27% |
| 40–59 | 3,021 | 1.80% | 4.81% | 14.39% |
| 60–79 | 2,248 | 1.49% | 4.98% | 14.86% |
| 80 and over | 1,207 | 1.38% | 4.69% | 14.85% |
| Hispanic | 1,259 | 2.12% | 3.81% | 12.56% |
| Non-Hispanic | 10,338 | 1.61% | 4.85% | 14.76% |
| White | 9,535 | 1.79% | 4.68% | 14.24% |
| Black | 965 | 1.06% | 6.01% | 15.37% |
| Asian | 780 | 1.12% | 4.08% | 15.53% |
| Other | 133 | 3.09% | 5.15% | 17.76% |
| Hawaiian | 130 | 0.00% | 0.93% | 17.27% |
| Native | 54 | 0.00% | 9.52% | 19.61% |

Group labels are Synthea's. No confidence intervals were calculated, and the three levels share the same people, so they are not independent. Groups of 54 to 133 people are too small to compare.

Women are split more than men at every level, and the injector can only give the maiden-name error to women, because only they have a maiden name in this data. That is a likely cause, but it was not tested separately.

False merges are too few to compare groups: 8, 6 and 8 people in total at the low, medium and high levels. At medium and high all of them were men, and the 80-and-over group had the highest rate of any age band at every level. The reason was not investigated.

## Explainability
Each comparison adds or removes evidence, measured as a match weight of log2(m/u). In the medium model, an exact agreement scores:

| Agreement | Match weight |
|---|---:|
| NHS number | 14.2 |
| First name and surname | 13.7 |
| Address | 13.6 |
| Date of birth | 12.9 |
| Postcode | 7.3 |
| Sex | 1.0 |

The chance that two random records match is about 7 in 100,000, so a pair needs about 20 points of total evidence to reach 0.99. No single field is enough on its own.

## Ethical considerations and UK GDPR
No real personal data is used. On real records, health data is special category under UK GDPR Article 9, and linkage would need a lawful basis and data protection impact assessment. Linkage errors affect people unevenly and can bias later analysis, so subgroup results should be re-run on real data. A human-in-the-loop review queue exists, but its decisions do not yet change the clusters.

## Limitations and risks
- Injected error rates are illustrative, so results do not predict real-world accuracy.
- The error injector and the model were designed by the same author, so the model may suit these errors better than it would suit real ones.
- In the low-error model, one rare comparison level (first name and surname swapped) had no estimated `u` value because no random pair reached it, so Splink used its default.
- Each model is trained on data with the same error level it is tested on. Performance when the error level changes was not measured.
- Results are one test population per level, with no confidence intervals.

## Monitoring
Not deployed. On a live feed, these signals would prompt re-estimating the model: changes in the data-quality gate's missing and invalid shares, in the match-probability distribution, in the review queue's size, or in reviewers' overturn rate.

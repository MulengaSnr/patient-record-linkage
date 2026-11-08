# Findings

_Written for a non-technical stakeholder: what we found, how confident we are, and what to do next._

**All of this is synthetic data.** The errors were added on purpose at rates chosen for this project, so the results show how the method behaves. They do not predict how accurate it would be on real NHS records.

## Key findings
1. **Probabilistic matching finds far more of the same patient's records than exact-match rules, and it is no less safe.** With a medium level of errors, it found 96.3% of true matches against 85.8% for the rules. It also wrongly merged fewer people: 0.05% against 0.57%.
2. **Its advantage grows as data gets worse.** With a high level of errors, it found 89.2% of true matches against 71.0%, and wrongly merged 0.07% of people against 1.83%.
3. **Wrong merges stayed rare at every error level.** The method was tuned to avoid them, because putting one patient's history on another's record is the more serious mistake. Between 6 and 8 people out of 11,597 were wrongly merged at each level.
4. **The cost of that caution is missed links.** With a high level of errors, 14.5% of people with several records still had those records split. At a medium level it was 4.7%.
5. **Women's records are split more often than men's.** This happens at every level: 2.0% against 1.3% at low, 5.7% against 3.8% at medium and 15.5% against 13.6% at high. Only women have a maiden name in this data, so only they can have a record under a former surname. In real data, gaps like this could make women's care look more fragmented than it is.
6. **Dates of birth and shortened names cause the most trouble.** At the high error level, records with a wrong or missing date of birth link 57% to 61% of the time, and first names cut to an initial 64%. Records with no error link 98% of the time.

| Error level | Matches found (Splink) | Matches found (rules) | People wrongly merged (Splink) | People wrongly merged (rules) |
|---|---:|---:|---:|---:|
| Low | 98.7% | 94.8% | 0.07% | 0.09% |
| Medium | 96.3% | 85.8% | 0.05% | 0.57% |
| High | 89.2% | 71.0% | 0.07% | 1.83% |

## Recommendations
- **Use probabilistic matching in place of exact rules** where records are incomplete or poorly recorded. On clean data the gain is smaller.
- **Send borderline pairs to a person to check.** The review queue exists for this, but decisions do not yet change the linked records, so that needs finishing before relying on it.
- **Check for uneven errors on any real data,** by sex, age and ethnicity, before using linked records for analysis.
- **Improve date-of-birth capture at source,** because errors there are among the hardest to recover from later.

## Caveats and limitations
- **The error rates are illustrative.** They were not measured from real systems.
- **The names and addresses are American,** so name patterns differ from those in the UK.
- **Small groups are unreliable.** Some ethnic groups have only 54 to 133 people here, so differences between them may be chance. Wrong merges are too few to compare groups at all.
- **Uncertainty ranges were not calculated,** so small differences should not be read as real.
- **The cause of the gap between women and men is likely but not proven.** It was not tested by removing the surname errors.
- **The test was run once, on purpose.** The method and threshold were fixed beforehand, so the results could not be tuned to look better.

# Patient Record Linkage Pipeline

Finding the same person across messy health records, using synthetic data, data-quality checks, Splink and Airflow.

**Status:** In development, step 5 of 9 (stable person IDs and review queue). Code for steps 4 and 5 is built and tested on a small pilot. **No linkage results yet:** those need the three full populations.

## The problem
The same patient often appears under several records, because of typos, changed names, missing dates and different hospitals. Duplicates split a patient's history, and wrongly merging two people is worse. This project links records probabilistically, gives each person a stable ID, and measures how accurate the linkage is and for whom.

**All data is synthetic.** No real patient data is used.

Design, decisions and evaluation rules: [docs/DESIGN.md](docs/DESIGN.md).

## Warehouse and data-quality gate
Source files are checked for shape, loaded unchanged into `raw`, then typed and standardised in `staging`. Each source's dates are parsed in that source's own format. Loading the same file twice adds nothing.

A quality gate then grades each source as OK, WARN or FAIL against thresholds in `configs/default.yaml`, and one FAIL stops the run. Results are saved first, so a failed run leaves evidence.

| Pilot dataset (1,145 people) | Records | Checks OK | Warnings | Failures |
|---|---:|---:|---:|---:|
| Low error | 2,445 | 28 | 0 | 0 |
| Medium error | 2,507 | 28 | 0 | 0 |
| High error | 2,639 | 27 | 1 | 0 |

The one warning is the GP feed's invalid NHS numbers (2.8%, warning at 2%). In a deliberate test, a GP file with every surname blanked stopped the run at `missing_surname`. The thresholds were set for this synthetic data and would need tuning on real feeds.

## Stable person IDs and clerical review
Splink's cluster IDs can change on every run, so each cluster inherits the existing person key it shares the most records with. A key belongs to only one cluster. When two people turn out to be one, the absorbed key redirects to the survivor, so references to it still resolve, and when a person is split, the larger part keeps the key. Each change is logged, and re-linking unchanged data changes no keys.

Pairs that scored fairly high but were not linked go to `linked.review_queue` for a person to check. A decided pair is never reopened. **Decisions are stored but do not yet change the clusters,** and there is no review screen.

## Run it
```bash
uv sync
cp .env.example .env   # then choose a password
make db-up             # local PostgreSQL in Docker
make check             # lint + tests (database tests need db-up)
make sources POP=pilot # needs Synthea output: see data/README.md
make warehouse POP=pilot LEVEL=medium
make linkage TRAIN=pilot/medium EVAL=pilot/medium
make publish DATASET=pilot/medium
```

## Author
**Enock Mulenga**, Data Scientist · [LinkedIn](https://www.linkedin.com/in/enock-mulenga-8472ba137) · [Portfolio](https://mulengasnr.github.io)

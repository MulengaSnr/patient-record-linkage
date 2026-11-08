# Patient Record Linkage Pipeline

Finding the same person across messy health records, using synthetic data, data-quality checks, Splink and Airflow.

**Status:** In development, step 6 of 9 (Airflow orchestration). Code for steps 4 to 6 is built and tested on a small pilot. **No linkage results yet:** those need the three full populations.

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

## Daily orchestration with Airflow
The `patient_linkage_daily` DAG processes one day at a time: `load_and_check` loads that day's records and applies the quality gate, then `link_and_publish` re-links everything received so far and updates the person keys. Daily loads are incremental, but linkage is a full re-link (design decision D7).

**Failure handling, tested by planting a corrupted feed on day 12 of 30:**
- The gate judges each day on its own, so one bad day cannot hide behind weeks of good data.
- The failed day's data is rolled back but its check results are kept, so a corrected file can replace it.
- One failed run pauses the DAG, so no later day starts.
- After fixing the file, `make airflow-resume DAY=2026-10-12` restarts from the failed day. In the test, all 30 days then completed.

Airflow runs as one container using about 1.0 GB idle and 1.4 GB at peak on the pilot. It has its own Python environment apart from the project's, because the two need different package versions. The truth table is never mounted into the container.

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
make airflow-up        # Airflow on http://127.0.0.1:8080, then unpause the DAG
```

## Author
**Enock Mulenga**, Data Scientist · [LinkedIn](https://www.linkedin.com/in/enock-mulenga-8472ba137) · [Portfolio](https://mulengasnr.github.io)

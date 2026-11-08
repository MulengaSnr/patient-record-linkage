# Patient Record Linkage Pipeline

Finding the same person across messy health records, using synthetic data, data-quality checks, Splink and Airflow.

**Status:** In development, step 3 of 9 (warehouse and data-quality gate). No linkage results yet.

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

## Run it
```bash
uv sync
cp .env.example .env   # then choose a password
make db-up             # local PostgreSQL in Docker
make check             # lint + tests (database tests need db-up)
make sources POP=pilot # needs Synthea output: see data/README.md
make warehouse POP=pilot LEVEL=low
```

## Author
**Enock Mulenga**, Data Scientist · [LinkedIn](https://www.linkedin.com/in/enock-mulenga-8472ba137) · [Portfolio](https://mulengasnr.github.io)

# Patient Record Linkage Pipeline

Finding the same person across messy health records, using synthetic data, data-quality checks, Splink and Airflow.

**Status:** In development, step 1 of 9 (scaffold and design). No results yet.

## The problem
The same patient often appears under several records, because of typos, changed names, missing dates and different hospitals. Duplicates split a patient's history, and wrongly merging two people is worse. This project links records probabilistically, gives each person a stable ID, and measures how accurate the linkage is and for whom.

**All data is synthetic.** No real patient data is used.

Design, decisions and evaluation rules: [docs/DESIGN.md](docs/DESIGN.md).

## Run it
```bash
uv sync
make check   # lint + tests
```

## Author
**Enock Mulenga**, Data Scientist · [LinkedIn](https://www.linkedin.com/in/enock-mulenga-8472ba137) · [Portfolio](https://mulengasnr.github.io)

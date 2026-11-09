# Power BI report

How to build the report from the files in `data/`. Power BI Desktop is Windows-only and the project runs in a Linux VM, so the report reads exported CSV files (decision D9 in `docs/DESIGN.md`).

**All data is synthetic.** The files hold keys, flags and counts. They contain no names, dates of birth, addresses or NHS numbers.

To refresh the files, run `make marts` (default `DATASET=pilot/medium-daily`, the 30-day Airflow run on the pilot population).

## 1. Load the files
For each of the seven CSV files: **Home > Get data > Text/CSV**, choose **65001: Unicode (UTF-8)**, then **Load**.

| File | One row per | Used on |
|---|---|---|
| `fact_records.csv` | record | Overview |
| `dim_people.csv` | active person | Overview, Review |
| `run_history.csv` | linkage run | Overview, Review |
| `dq_checks.csv` | check, per load attempt | Data quality |
| `review_queue.csv` | pair awaiting review | Review |
| `linkage_results.csv` | error level and method | Model results |
| `recall_by_error.csv` | error level, method and injected error | Model results |

Check the types in **Transform data**: `value`, `warn_at`, `fail_at`, `match_probability`, `linked_share` and the rate columns should be Decimal number; `finished_at_utc` should be Date/Time.

## 2. Model
- Create one relationship: `dim_people[person_key]` (one) to `fact_records[person_key]` (many), single direction.
- Leave the other tables unrelated. Each one feeds its own page.
- Remove any relationship Power BI detected automatically on `dataset` or `source`.
- For `linkage_results[error_level]` and `recall_by_error[error_level]`: **Column tools > Sort by column > `level_order`**, so charts read low, medium, high.

## 3. Measures
Create these with **Modeling > New measure**.

```dax
Records = COUNTROWS ( fact_records )

People = COUNTROWS ( dim_people )

Records per person = DIVIDE ( [Records], [People] )

People with several records = CALCULATE ( [People], dim_people[records] > 1 )

People with conflicting NHS numbers =
CALCULATE ( [People], dim_people[conflicting_nhs_numbers] = "Yes" )

Warnings =
CALCULATE (
    COUNTROWS ( dq_checks ),
    dq_checks[status] = "WARN",
    dq_checks[latest_attempt] = "Yes"
)

Batches stopped by the gate =
CALCULATE ( COUNTROWS ( dq_checks ), dq_checks[status] = "FAIL" )

Share affected =
DIVIDE (
    CALCULATE (
        SUM ( dq_checks[affected_records] ),
        dq_checks[check_type] = "Share",
        dq_checks[latest_attempt] = "Yes"
    ),
    CALCULATE (
        SUM ( dq_checks[records_in_batch] ),
        dq_checks[check_type] = "Share",
        dq_checks[latest_attempt] = "Yes"
    )
)

Open review pairs =
CALCULATE ( COUNTROWS ( review_queue ), review_queue[status] = "open" )
```

Format `Share affected` as a percentage with one decimal place, and `Records per person` with two. Always use `Share affected` rather than averaging `value`: batches differ in size, and a plain average gives small batches too much weight.

## 4. Pages
Put "Synthetic data: no real patients" in the footer of every page.

**Overview: how many people are behind these records?**
- Cards: `Records`, `People`, `Records per person`, `People with several records`
- Bar chart: `People` by `dim_people[source_combination]`, sorted descending
- Line chart: `run_history[records]` and `run_history[people]` by `run_number`. People grow more slowly than records as new records match existing people.

**Data quality: can we trust each feed?**
- Cards: `Warnings`, `Batches stopped by the gate`
- Matrix: `dq_checks[check_name]` by `dq_checks[source]`, showing `Share affected`, with a page filter of `check_type` = Share
- Line chart: `Share affected` by `batch_day`, with `source` as the legend and a slicer on `check_name`
- Table: filtered to `status` = FAIL, showing `batch_day`, `attempt`, `source`, `check_name`, `affected_records`, `records_in_batch`. This is the corrupted GP file on day 12, which was stopped and then corrected.

**Review: what is left for a person to check?**
- Cards: `Open review pairs`, `People with conflicting NHS numbers`
- Column chart: `Open review pairs` by `probability_band`
- Bar chart: `Open review pairs` by `source_pair`
- Line chart: `run_history[open_review_pairs]` by `run_number`

**Model results: is the model better than the rules?**
- Clustered column chart: `linkage_results[recall]` by `error_level`, with `method` as the legend. Do the same for `split_rate`.
- Bar chart: average of `recall_by_error[linked_share]` by `injected_error`, with a page filter of `method` = Splink and a slicer on `error_level`
- Note on the page: "Held-out test population of 11,597 people, which is separate from the 30-day pilot on the other pages."

## 5. Check the numbers
A report that disagrees with these has a modelling mistake, most often a stray relationship or a missing `latest_attempt` filter.

| Item | Expected |
|---|---|
| `Records` | 2,507 (GP 1,064, Hospital 839, Lab 604) |
| `People` | 1,213 |
| `Records per person` | 2.07 |
| `People with several records` | 870 |
| `People with conflicting NHS numbers` | 3 |
| `Warnings` | 31 |
| `Batches stopped by the gate` | 1 (day 12, GP, `missing_surname`, 38 of 38 records) |
| `Share affected`, `missing_postcode`, GP | 27.4% |
| `Share affected`, `missing_postcode`, Hospital | 32.8% |
| `Open review pairs` | 255 |
| Recall at high errors | Splink 89.15%, Baseline 70.95% |

## 6. What to save
- The report as `powerbi/patient_linkage.pbix`
- One screenshot of each page in `reports/figures/`, named `powerbi-overview.png`, `powerbi-data-quality.png`, `powerbi-review.png` and `powerbi-model-results.png`

Power BI stores absolute paths to the CSV files. Anyone else opening the `.pbix` must point them at their own copy with **Transform data > Data source settings**.

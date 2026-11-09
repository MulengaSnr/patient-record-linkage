# Runbook

How to start, check, recover and back up the patient linkage pipeline. Each procedure says whether it has actually been exercised. All data is synthetic, and everything runs on one machine at no cost.

## What runs

| Part | Where | Started by | Needs |
|---|---|---|---|
| PostgreSQL warehouse | Docker, `127.0.0.1:5433` | `make db-up` | `.env` |
| Airflow | Docker, <http://127.0.0.1:8080>, no login, this machine only | `make airflow-up` | The warehouse |
| Dashboard | Local process, <http://127.0.0.1:8050> | `make app` | Only the CSV files in `app/data/` |
| PySpark job | Local process, on demand | `make spark` | Java 17 or 21, and the warehouse for its comparison |

**Before you start:** Docker, [uv](https://docs.astral.sh/uv/), and `cp .env.example .env` with your own values. If Java is not on your `PATH`, set `JAVA_HOME` in `.env`. Only `make spark` and its tests need Java.

Airflow is capped at 3 GB. On the 7.3 GB development VM it used about 1.2 GB when idle.

## Start, stop and check
_Exercised on 9 November 2026, including a rebuild of the Airflow image._

```bash
make db-up          # waits until PostgreSQL is healthy
make airflow-up     # builds the image if needed; healthy after about 25 seconds
curl -s http://127.0.0.1:8080/api/v2/monitor/health

make airflow-down   # stops Airflow
make db-down        # stops PostgreSQL; data is kept
```

The Airflow image must not contain Spark or Shiny. They are in separate dependency groups, and its build uses `--no-default-groups`.

## The daily pipeline
_Exercised on the 1,145-person pilot for all 30 simulated days. Not yet run at full population size._

The `patient_linkage_daily` DAG starts paused, so unpause it in the Airflow page. It runs one simulated day at a time, from `2026-10-01` (day 1) to `2026-10-30` (day 30), and each day has two tasks: `load_and_check`, then `link_and_publish`.

These runs use the dataset label `pilot/medium-daily`, which is kept apart from `pilot/medium`.

## When the quality gate stops a day
_Exercised by planting a corrupted GP file on day 12 (design decisions D13 to D15)._

What you will see: `load_and_check` has failed, `link_and_publish` did not run, and the DAG has paused itself, so no later day starts. The failed day's rows were rolled back and its check results were kept.

1. Find what failed:
   ```bash
   docker compose exec -T postgres psql -U linkage -d warehouse -c "
     SELECT batch_day, source, check_name, round(value::numeric, 3) AS value, fail_at
     FROM dq.check_results WHERE status = 'FAIL' ORDER BY checked_at DESC LIMIT 10;"
   ```
2. Correct the file on the host, in `data/processed/sources/<population>/<level>/<source>.csv`. The container mounts this folder read-only.
3. Restart from that day. Its date is `2026-10-01` plus the day number minus one, so day 12 is:
   ```bash
   make airflow-resume DAY=2026-10-12
   ```

The later days then run in order. Do not change a threshold to get past a failure, unless you have decided the threshold itself is wrong.

## Common errors

| Message or symptom | Cause | Fix |
|---|---|---|
| `Copy .env.example to .env and set a password` | No `.env` file | `cp .env.example .env`, then set the values |
| `WAREHOUSE_DSN is not set` | Command run outside `make`, so `.env` was not loaded | Use the `make` target |
| `day N is not loaded, so day N+1 cannot be loaded yet` | A day was skipped | Load the missing day first |
| `make spark` reports differences from `staging.records` | The Spark and SQL rules have diverged, or the warehouse has not loaded that dataset | Run `make warehouse` for the dataset, then compare the rules listed in the log |
| Spark tests are skipped | Java not found | Set `JAVA_HOME` in `.env` |
| `make marts` reports `No records for dataset` | Wrong label, or the dataset is not loaded | Check the label. No file is overwritten |
| The final `make linkage` run refuses to start | The test population is used once, by design | Do not work around this. It is what makes the test result valid |
| Airflow container stops under load | Reached its 3 GB limit. Not seen so far | Stop other workloads, then resume the failed day |

## Clerical review
_The update below was tested in a transaction that was rolled back._

Open pairs are in `linked.review_queue`, most likely matches first:

```bash
docker compose exec -T postgres psql -U linkage -d warehouse -c "
  SELECT left_id, right_id, round(match_probability::numeric, 3) AS probability
  FROM linked.review_queue
  WHERE dataset = 'pilot/medium-daily' AND status = 'open'
  ORDER BY match_probability DESC LIMIT 20;"
```

Record a decision with `status` set to `match` or `non_match`:

```sql
UPDATE linked.review_queue
SET status = 'match', decided_at = now()
WHERE dataset = 'pilot/medium-daily' AND left_id = 'G0000287' AND right_id = 'H0000834';
```

A decided pair is never reopened. **Decisions are stored but do not yet change the clusters,** so recording a match does not merge those people.

## Refresh the dashboard
_Exercised._

```bash
make marts          # default DATASET=pilot/medium-daily; rewrites app/data/
make app            # http://127.0.0.1:8050
```

The dashboard reads the files once at start-up, so restart it after `make marts`. Commit the new files if they should replace the published ones. `tests/test_dashboard.py` checks the published totals, so it fails if a different dataset was exported.

## Back up and restore
_Backup and restore into an empty database exercised on 9 November 2026, with matching row counts in every table checked. Restoring over the live `warehouse` database has not been drilled._

Source files can be regenerated, but **person key history and review decisions exist only in the warehouse**.

```bash
docker compose exec -T postgres pg_dump -U linkage -d warehouse -Fc > warehouse.dump

# Restore into a new database and check it before relying on it
docker compose exec -T postgres psql -U linkage -d postgres -c "CREATE DATABASE restore_check"
docker compose exec -T postgres pg_restore -U linkage -d restore_check --no-owner < warehouse.dump
```

The dump is about 15 MB. Keep it out of the repository.

## Start again from nothing
_Not drilled. This permanently deletes the warehouse and the Airflow history._

```bash
docker compose --profile airflow down -v
```

Back up first if review decisions matter. Then rebuild with `make db-up`, and run `make warehouse` and `make publish` for each dataset.

## Run the daily pipeline at full size
_Not done. This is the main untested operation._

The DAG reads `LINKAGE_POPULATION`, `LINKAGE_LEVEL`, `LINKAGE_LABEL` and `LINKAGE_RESULTS`, but `compose.yaml` does not pass them to the container yet, so add them under the Airflow service first. Use `tune` or `train` rather than `test`, and a results file from `data/processed/linkage/`. One linkage run at full size peaked at about 670 MB outside Airflow. Airflow's own memory use at full size is unmeasured, so watch `docker stats` during the first run.

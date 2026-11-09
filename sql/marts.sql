-- Reporting views for the dashboard. They hold no data, so rebuilding them is safe.
-- They carry keys and flags only: no names, dates of birth, addresses or NHS
-- numbers leave the warehouse through this layer.
DROP SCHEMA IF EXISTS mart CASCADE;
CREATE SCHEMA mart;

CREATE FUNCTION mart.source_label(value text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN value = 'gp' THEN 'GP' ELSE initcap(value) END
$$;

CREATE FUNCTION mart.yes_no(value boolean)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN value THEN 'Yes' ELSE 'No' END
$$;

-- One row per record. Only batches that passed the gate reach staging.
CREATE VIEW mart.fact_records AS
SELECT
    s.dataset,
    s.record_id,
    mart.source_label(s.source) AS source,
    s.batch_day,
    r.person_key,
    CASE
        WHEN s.nhs_number IS NOT NULL THEN 'Valid'
        WHEN s.nhs_was_invalid THEN 'Invalid'
        ELSE 'Missing'
    END AS nhs_status,
    CASE
        WHEN s.date_of_birth IS NOT NULL THEN 'Valid'
        WHEN s.dob_unparseable THEN 'Unparseable'
        ELSE 'Missing'
    END AS dob_status,
    coalesce(s.sex, 'Unknown') AS sex
FROM staging.records AS s
LEFT JOIN linked.record_people AS r USING (dataset, record_id);

-- One row per active person. Merged keys are left out, so people are not
-- counted twice. Two different valid NHS numbers on one person can mean a
-- false merge or a wrong number on one record, so it is a prompt to check.
CREATE VIEW mart.dim_people AS
SELECT
    p.dataset,
    p.person_key,
    count(*) AS records,
    count(DISTINCT s.source) AS sources,
    string_agg(
        DISTINCT mart.source_label(s.source), ' + '
        ORDER BY mart.source_label(s.source)
    ) AS source_combination,
    min(s.batch_day) AS first_batch_day,
    count(DISTINCT s.nhs_number) AS distinct_nhs_numbers,
    mart.yes_no(count(DISTINCT s.nhs_number) > 1) AS conflicting_nhs_numbers
FROM linked.people AS p
JOIN linked.record_people AS r USING (dataset, person_key)
JOIN staging.records AS s
    ON s.dataset = r.dataset AND s.record_id = r.record_id
WHERE p.status = 'active'
GROUP BY p.dataset, p.person_key;

-- One row per check per load attempt. A corrected day has several attempts:
-- report on latest_attempt = 'Yes' to avoid counting that day twice, and on
-- the earlier attempts to show what the gate stopped.
CREATE VIEW mart.dq_checks AS
WITH runs AS (
    SELECT dataset, batch_day, run_id, min(checked_at) AS started
    FROM dq.check_results
    GROUP BY dataset, batch_day, run_id
),
attempts AS (
    SELECT
        run_id,
        row_number() OVER day_runs AS attempt,
        count(*) OVER (PARTITION BY dataset, batch_day) AS attempts
    FROM runs
    WINDOW day_runs AS (PARTITION BY dataset, batch_day ORDER BY started)
)
SELECT
    d.dataset,
    d.batch_day,
    a.attempt,
    mart.yes_no(a.attempt = a.attempts) AS latest_attempt,
    mart.source_label(d.source) AS source,
    d.check_name,
    CASE WHEN d.check_name = 'record_count' THEN 'Count' ELSE 'Share' END
        AS check_type,
    d.value,
    d.warn_at,
    d.fail_at,
    d.status,
    size.value::integer AS records_in_batch,
    CASE
        WHEN d.check_name <> 'record_count' THEN round(d.value * size.value)::integer
    END AS affected_records
FROM dq.check_results AS d
JOIN attempts AS a USING (run_id)
JOIN dq.check_results AS size
    ON size.run_id = d.run_id
    AND size.source = d.source
    AND size.check_name = 'record_count';

-- One row per linkage run, in the order they ran.
CREATE VIEW mart.run_history AS
SELECT
    dataset,
    row_number() OVER (PARTITION BY dataset ORDER BY finished_at) AS run_number,
    to_char(finished_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS finished_at_utc,
    threshold,
    records,
    people,
    created,
    merged,
    split,
    moved_records,
    open_review_pairs
FROM linked.runs;

-- One row per candidate pair for clerical review.
CREATE VIEW mart.review_queue AS
SELECT
    q.dataset,
    q.left_id,
    q.right_id,
    least(mart.source_label(l.source), mart.source_label(r.source))
        || ' / '
        || greatest(mart.source_label(l.source), mart.source_label(r.source))
        AS source_pair,
    q.match_probability,
    to_char(least(floor(q.match_probability * 10) / 10, 0.9), 'FM0.0')
        || ' to '
        || to_char(least(floor(q.match_probability * 10) / 10, 0.9) + 0.1, 'FM0.0')
        AS probability_band,
    q.status
FROM linked.review_queue AS q
LEFT JOIN linked.record_people AS l
    ON l.dataset = q.dataset AND l.record_id = q.left_id
LEFT JOIN linked.record_people AS r
    ON r.dataset = q.dataset AND r.record_id = q.right_id;

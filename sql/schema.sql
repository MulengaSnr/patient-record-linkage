-- Warehouse layers: raw (as received), staging (typed and standardised) and dq
-- (data-quality results). Safe to run repeatedly.
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS dq;
CREATE SCHEMA IF NOT EXISTS linked;

CREATE TABLE IF NOT EXISTS raw.load_audit (
    load_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset       text NOT NULL,
    source        text NOT NULL,
    file_sha256   text NOT NULL,
    rows_in_file  integer NOT NULL,
    rows_inserted integer NOT NULL DEFAULT 0,
    loaded_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (dataset, source, file_sha256)
);

-- Everything is text here, so a malformed value is kept rather than rejected.
CREATE TABLE IF NOT EXISTS raw.records (
    dataset       text NOT NULL,
    source        text NOT NULL,
    record_id     text NOT NULL,
    nhs_number    text,
    first_name    text,
    middle_name   text,
    surname       text,
    date_of_birth text,
    sex           text,
    address       text,
    city          text,
    postcode      text,
    batch_day     text NOT NULL,
    load_id       bigint NOT NULL REFERENCES raw.load_audit (load_id),
    PRIMARY KEY (dataset, source, record_id)
);

CREATE TABLE IF NOT EXISTS staging.records (
    dataset          text NOT NULL,
    source           text NOT NULL,
    record_id        text NOT NULL,
    nhs_number       text,
    nhs_was_invalid  boolean NOT NULL,
    first_name       text,
    middle_name      text,
    surname          text,
    date_of_birth    date,
    dob_unparseable  boolean NOT NULL,
    sex              text,
    address          text,
    city             text,
    postcode         text,
    batch_day        integer NOT NULL,
    PRIMARY KEY (dataset, source, record_id)
);

CREATE TABLE IF NOT EXISTS dq.check_results (
    run_id     uuid NOT NULL,
    dataset    text NOT NULL,
    source     text NOT NULL,
    check_name text NOT NULL,
    value      double precision NOT NULL,
    warn_at    double precision,
    fail_at    double precision,
    status     text NOT NULL CHECK (status IN ('OK', 'WARN', 'FAIL')),
    checked_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, source, check_name)
);

CREATE TABLE IF NOT EXISTS linked.runs (
    run_id            uuid PRIMARY KEY,
    dataset           text NOT NULL,
    threshold         double precision NOT NULL,
    records           integer,
    people            integer,
    created           integer,
    merged            integer,
    split             integer,
    moved_records     integer,
    open_review_pairs integer,
    finished_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS linked.people (
    dataset     text NOT NULL,
    person_key  text NOT NULL,
    merged_into text,
    status      text GENERATED ALWAYS AS
                    (CASE WHEN merged_into IS NULL THEN 'active' ELSE 'merged' END) STORED,
    created_run uuid NOT NULL REFERENCES linked.runs (run_id),
    PRIMARY KEY (dataset, person_key)
);

CREATE TABLE IF NOT EXISTS linked.record_people (
    dataset    text NOT NULL,
    record_id  text NOT NULL,
    source     text NOT NULL,
    person_key text NOT NULL,
    run_id     uuid NOT NULL REFERENCES linked.runs (run_id),
    PRIMARY KEY (dataset, record_id),
    FOREIGN KEY (dataset, person_key) REFERENCES linked.people (dataset, person_key)
);

CREATE TABLE IF NOT EXISTS linked.person_events (
    run_id      uuid NOT NULL REFERENCES linked.runs (run_id),
    dataset     text NOT NULL,
    event       text NOT NULL CHECK (event IN ('created', 'merged', 'split')),
    person_key  text NOT NULL,
    related_key text
);

CREATE TABLE IF NOT EXISTS linked.review_queue (
    dataset           text NOT NULL,
    left_id           text NOT NULL,
    right_id          text NOT NULL,
    match_probability double precision NOT NULL,
    status            text NOT NULL DEFAULT 'open'
                          CHECK (status IN ('open', 'match', 'non_match')),
    run_id            uuid NOT NULL REFERENCES linked.runs (run_id),
    decided_at        timestamptz,
    PRIMARY KEY (dataset, left_id, right_id)
);

-- Which batch a check judged. NULL means the whole dataset.
ALTER TABLE dq.check_results ADD COLUMN IF NOT EXISTS batch_day integer;

-- A date only if the text really is that date in that format.
CREATE OR REPLACE FUNCTION staging.safe_date(value text, format text)
RETURNS date LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    parsed date;
BEGIN
    parsed := to_date(value, format);
    IF to_char(parsed, format) = value THEN
        RETURN parsed;
    END IF;
    RETURN NULL;
EXCEPTION WHEN others THEN
    RETURN NULL;
END;
$$;

-- Modulus 11 check, matching patient_linkage.data.population.is_valid_nhs_number.
CREATE OR REPLACE FUNCTION staging.nhs_is_valid(value text)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN value IS NULL OR value !~ '^[0-9]{10}$' THEN false
        ELSE (
            SELECT CASE
                       WHEN 11 - total % 11 = 11 THEN 0
                       ELSE 11 - total % 11
                   END = substr(value, 10, 1)::integer
            FROM (
                SELECT sum(substr(value, i, 1)::integer * (11 - i)) AS total
                FROM generate_series(1, 9) AS i
            ) AS weighted
        )
    END
$$;

-- Letters and single spaces only, in upper case, or NULL if nothing is left.
CREATE OR REPLACE FUNCTION staging.clean_name(value text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT nullif(
        trim(regexp_replace(
            regexp_replace(upper(value), '[^[:alpha:] ]', '', 'g'), '\s+', ' ', 'g'
        )),
        ''
    )
$$;

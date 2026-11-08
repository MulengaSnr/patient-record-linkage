-- Rebuild one source's staging rows from raw.
INSERT INTO staging.records (
    dataset, source, record_id, nhs_number, nhs_was_invalid, first_name,
    middle_name, surname, date_of_birth, dob_unparseable, sex, address, city,
    postcode, batch_day
)
SELECT
    dataset,
    source,
    record_id,
    CASE WHEN staging.nhs_is_valid(nhs_number) THEN nhs_number END,
    nhs_number IS NOT NULL AND NOT staging.nhs_is_valid(nhs_number),
    staging.clean_name(first_name),
    staging.clean_name(middle_name),
    staging.clean_name(surname),
    staging.safe_date(date_of_birth, %(date_format)s),
    date_of_birth IS NOT NULL
        AND staging.safe_date(date_of_birth, %(date_format)s) IS NULL,
    CASE WHEN upper(sex) IN ('M', 'F') THEN upper(sex) END,
    nullif(trim(regexp_replace(upper(address), '\s+', ' ', 'g')), ''),
    nullif(trim(regexp_replace(upper(city), '\s+', ' ', 'g')), ''),
    CASE WHEN postcode ~ '^[0-9]{5}$' THEN postcode END,
    batch_day::integer
FROM raw.records
WHERE dataset = %(dataset)s AND source = %(source)s

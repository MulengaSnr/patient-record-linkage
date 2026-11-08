"""Read standardised records from the warehouse for linkage."""

from __future__ import annotations

import pandas as pd
import psycopg

_QUERY = """
    SELECT
        record_id AS unique_id,
        source,
        nhs_number,
        first_name,
        surname,
        CASE
            WHEN first_name IS NOT NULL AND surname IS NOT NULL
            THEN first_name || ' ' || surname
        END AS first_name_surname,
        to_char(date_of_birth, 'YYYY-MM-DD') AS date_of_birth,
        sex,
        address,
        postcode
    FROM staging.records
    WHERE dataset = %s
    ORDER BY record_id
"""


def read_records(conn: psycopg.Connection, dataset: str) -> pd.DataFrame:
    """Staging records for one dataset, in the form Splink expects.

    Args:
        conn: Open connection.
        dataset: Dataset label, for example ``pilot/medium``.

    Returns:
        One row per record, with missing values as ``None``.

    Raises:
        ValueError: If the dataset has no records.
    """
    with conn.cursor() as cursor:
        cursor.execute(_QUERY, (dataset,))
        columns = [column.name for column in cursor.description]
        rows = cursor.fetchall()
    if not rows:
        raise ValueError(f"No staging records for dataset {dataset!r}")
    return pd.DataFrame(rows, columns=columns, dtype=object)

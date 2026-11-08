"""Check source files, then load them into the raw and staging layers."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.pandas as pa
import psycopg

from patient_linkage.config import PROJECT_ROOT

RAW_FIELDS = (
    "record_id",
    "nhs_number",
    "first_name",
    "middle_name",
    "surname",
    "date_of_birth",
    "sex",
    "address",
    "city",
    "postcode",
    "batch_day",
)
SQL_DIR = PROJECT_ROOT / "sql"


def connect(variable: str = "WAREHOUSE_DSN") -> psycopg.Connection:
    """Open a connection using the DSN held in an environment variable.

    Args:
        variable: Name of the environment variable.

    Returns:
        An open connection.

    Raises:
        RuntimeError: If the variable is not set.
    """
    dsn = os.environ.get(variable)
    if not dsn:
        raise RuntimeError(f"{variable} is not set: copy .env.example to .env")
    return psycopg.connect(dsn)


def apply_schema(conn: psycopg.Connection) -> None:
    """Create the warehouse tables and functions if they do not exist."""
    conn.execute((SQL_DIR / "schema.sql").read_text())


def read_source(path: Path | str) -> pd.DataFrame:
    """Read a source file with every value as text.

    Only an empty field counts as missing. By default pandas also treats words
    such as "NA" and "Null" as missing, which would erase real surnames.

    Args:
        path: Location of the CSV file.

    Returns:
        The file's rows.
    """
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])


def file_schema(source: dict[str, Any]) -> pa.DataFrameSchema:
    """The shape a source file must have before it may be loaded.

    Args:
        source: One entry of ``linkage_data.sources``.

    Returns:
        A schema that rejects missing or unexpected columns.
    """
    columns = {
        "record_id": pa.Column(
            checks=pa.Check.str_matches(rf"^{source['prefix']}\d{{7}}$"),
            unique=True,
            nullable=False,
        ),
        "batch_day": pa.Column(checks=pa.Check.str_matches(r"^\d+$"), nullable=False),
    }
    columns |= {field: pa.Column(nullable=True) for field in source["fields"]}
    return pa.DataFrameSchema(columns, strict=True)


def load_source(
    conn: psycopg.Connection,
    dataset: str,
    source: str,
    frame: pd.DataFrame,
    file_sha256: str,
) -> int:
    """Copy one file into ``raw.records``; loading the same file again does nothing.

    Args:
        conn: Open connection. The caller commits.
        dataset: Dataset label, for example ``pilot/low``.
        source: Source system name.
        frame: Validated file contents.
        file_sha256: Checksum of the file.

    Returns:
        The number of rows newly inserted.
    """
    audit = conn.execute(
        """
        INSERT INTO raw.load_audit (dataset, source, file_sha256, rows_in_file)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (dataset, source, file_sha256) DO NOTHING
        RETURNING load_id
        """,
        (dataset, source, file_sha256, len(frame)),
    ).fetchone()
    if audit is None:
        return 0
    load_id = audit[0]

    columns = ", ".join(RAW_FIELDS)
    conn.execute("DROP TABLE IF EXISTS _incoming")
    conn.execute(
        "CREATE TEMP TABLE _incoming ("
        + ", ".join(f"{field} text" for field in RAW_FIELDS)
        + ") ON COMMIT DROP"
    )
    rows = frame.reindex(columns=list(RAW_FIELDS))
    with (
        conn.cursor() as cursor,
        cursor.copy(f"COPY _incoming ({columns}) FROM STDIN") as copy,
    ):
        for row in rows.itertuples(index=False, name=None):
            copy.write_row([None if pd.isna(value) else value for value in row])
    inserted = conn.execute(
        f"""
        INSERT INTO raw.records (dataset, source, {columns}, load_id)
        SELECT %s, %s, {columns}, %s FROM _incoming
        ON CONFLICT (dataset, source, record_id) DO NOTHING
        """,
        (dataset, source, load_id),
    ).rowcount
    conn.execute(
        "UPDATE raw.load_audit SET rows_inserted = %s WHERE load_id = %s",
        (inserted, load_id),
    )
    return inserted


def standardise(
    conn: psycopg.Connection, dataset: str, source: str, date_format: str
) -> int:
    """Rebuild one source's staging rows from raw.

    Args:
        conn: Open connection. The caller commits.
        dataset: Dataset label.
        source: Source system name.
        date_format: PostgreSQL format of this source's dates.

    Returns:
        The number of staging rows written.
    """
    conn.execute(
        "DELETE FROM staging.records WHERE dataset = %s AND source = %s",
        (dataset, source),
    )
    return conn.execute(
        (SQL_DIR / "standardise.sql").read_text(),
        {"dataset": dataset, "source": source, "date_format": date_format},
    ).rowcount


def frame_checksum(frame: pd.DataFrame) -> str:
    """SHA-256 of a frame's contents, for loads of part of a file."""
    return hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest()


def file_checksum(path: Path | str) -> str:
    """SHA-256 of a file."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

import os
from pathlib import Path

import numpy as np
import psycopg
import pytest
from test_generate import REFERENCE, SETTINGS, write_patients

from patient_linkage.data.generate import build_sources
from patient_linkage.data.population import load_people
from patient_linkage.warehouse.load import apply_schema


@pytest.fixture
def conn():
    dsn = os.environ.get("WAREHOUSE_TEST_DSN")
    if not dsn:
        if os.environ.get("CI"):
            pytest.fail("WAREHOUSE_TEST_DSN must be set in CI")
        pytest.skip("WAREHOUSE_TEST_DSN not set")
    try:
        connection = psycopg.connect(dsn)
    except psycopg.OperationalError as error:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"Test database not reachable: {error}")
    with connection:
        connection.execute("DROP SCHEMA IF EXISTS raw, staging, dq CASCADE")
        connection.commit()
        apply_schema(connection)
        connection.commit()
        yield connection


@pytest.fixture
def folder(tmp_path) -> Path:
    people = load_people(write_patients(tmp_path, 400), np.random.default_rng(1))
    tables, _ = build_sources(
        people,
        SETTINGS,
        SETTINGS["error_levels"]["high"],
        REFERENCE,
        np.random.default_rng(2),
    )
    out = tmp_path / "sources"
    out.mkdir()
    for name, table in tables.items():
        table.to_csv(out / f"{name}.csv", index=False)
    return out

"""Turn Synthea's patients file into a clean base population.

The result is the "true" identity of each synthetic person, before any errors
are injected. It also gives each person a synthetic NHS-style number from the
999 range, which is set aside for testing and never issued to patients.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

_COLUMNS = {
    "Id": "person_id",
    "FIRST": "first_name",
    "MIDDLE": "middle_name",
    "LAST": "surname",
    "MAIDEN": "maiden_name",
    "BIRTHDATE": "date_of_birth",
    "GENDER": "sex",
    "ADDRESS": "address",
    "CITY": "city",
    "ZIP": "postcode",
    "RACE": "race",
    "ETHNICITY": "ethnicity",
}
_NAME_COLUMNS = ("first_name", "middle_name", "surname", "maiden_name")
_TRAILING_DIGITS = re.compile(r"\d+$")
_WEIGHTS = tuple(range(10, 1, -1))


def strip_name_digits(name: str | float | None) -> str | None:
    """Remove the digits Synthea appends to names ("Wilfredo622" -> "Wilfredo").

    Args:
        name: A name, or a missing value.

    Returns:
        The cleaned name, or ``None`` if nothing is left.
    """
    if not isinstance(name, str):
        return None
    return _TRAILING_DIGITS.sub("", name).strip() or None


def nhs_check_digit(first_nine: str) -> int | None:
    """Modulus 11 check digit for the first nine digits of an NHS number.

    Args:
        first_nine: A string of nine digits.

    Returns:
        The check digit, or ``None`` if these digits cannot form a valid number.

    Raises:
        ValueError: If the input is not nine digits.
    """
    if len(first_nine) != 9 or not first_nine.isdigit():
        raise ValueError(f"Expected nine digits, got {first_nine!r}")
    total = sum(int(d) * w for d, w in zip(first_nine, _WEIGHTS, strict=True))
    check = 11 - total % 11
    if check == 10:
        return None
    return 0 if check == 11 else check


def is_valid_nhs_number(number: str) -> bool:
    """Whether a ten-digit string has a correct NHS check digit."""
    if len(number) != 10 or not number.isdigit():
        return False
    return nhs_check_digit(number[:9]) == int(number[9])


def reserved_range_nhs_numbers(count: int, rng: np.random.Generator) -> list[str]:
    """Distinct valid NHS numbers, all from the reserved 999 test range.

    Args:
        count: How many numbers to create.
        rng: Random generator.

    Returns:
        Ten-digit strings beginning with 999.

    Raises:
        ValueError: If the test range cannot supply ``count`` numbers.
    """
    if count > 900_000:
        raise ValueError("The 999 test range cannot supply this many numbers")
    numbers: list[str] = []
    for suffix in rng.permutation(1_000_000):
        first_nine = f"999{int(suffix):06d}"
        check = nhs_check_digit(first_nine)
        if check is not None:
            numbers.append(f"{first_nine}{check}")
            if len(numbers) == count:
                break
    return numbers


def load_people(path: Path | str, rng: np.random.Generator) -> pd.DataFrame:
    """Read Synthea's ``patients.csv`` into a clean base population.

    Args:
        path: Location of ``patients.csv``.
        rng: Random generator for assigning NHS numbers.

    Returns:
        One row per person, sorted by ``person_id`` so results do not depend on
        file order.
    """
    raw = pd.read_csv(path, dtype=str, usecols=list(_COLUMNS))
    people = raw.rename(columns=_COLUMNS)[list(_COLUMNS.values())]
    for column in _NAME_COLUMNS:
        people[column] = people[column].map(strip_name_digits).astype(object)
    people["date_of_birth"] = pd.to_datetime(people["date_of_birth"]).dt.date
    # Synthea uses 00000 as a placeholder. Left in, it would look like a shared
    # postcode between unrelated people and inflate false matches.
    people["postcode"] = people["postcode"].where(people["postcode"] != "00000")
    people = people.sort_values("person_id", ignore_index=True)
    people["nhs_number"] = reserved_range_nhs_numbers(len(people), rng)
    # NaN counts as true in Python, so missing values must be None here.
    return people.astype(object).where(people.notna(), None)

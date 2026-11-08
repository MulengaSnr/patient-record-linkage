"""Inject realistic errors into one person's record.

Every function takes an explicit random generator, so a seed reproduces the
same errors. Each error applied is reported by name, which later allows linkage
accuracy to be broken down by error type.
"""

from __future__ import annotations

import datetime as dt
import string
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

NICKNAMES = {
    "Alexander": "Alex",
    "Andrew": "Andy",
    "Anthony": "Tony",
    "Benjamin": "Ben",
    "Catherine": "Kate",
    "Charles": "Charlie",
    "Christopher": "Chris",
    "Daniel": "Dan",
    "David": "Dave",
    "Edward": "Ed",
    "Elizabeth": "Liz",
    "Harold": "Harry",
    "James": "Jim",
    "Jennifer": "Jen",
    "Jonathan": "Jon",
    "Joseph": "Joe",
    "Joshua": "Josh",
    "Katherine": "Katie",
    "Margaret": "Maggie",
    "Matthew": "Matt",
    "Michael": "Mike",
    "Nicholas": "Nick",
    "Patricia": "Pat",
    "Patrick": "Pat",
    "Rebecca": "Becky",
    "Richard": "Rick",
    "Robert": "Bob",
    "Samuel": "Sam",
    "Stephen": "Steve",
    "Steven": "Steve",
    "Susan": "Sue",
    "Thomas": "Tom",
    "Timothy": "Tim",
    "William": "Bill",
}


def typo(value: str, rng: np.random.Generator) -> str:
    """Apply one substitution, deletion, insertion or adjacent swap.

    The first character is left alone, so a capitalised name stays capitalised.

    Args:
        value: Text to alter.
        rng: Random generator.

    Returns:
        The altered text, or ``value`` unchanged if it is under three characters.
    """
    if len(value) < 3:
        return value
    position = int(rng.integers(1, len(value) - 1))
    letter = str(rng.choice(list(string.ascii_lowercase)))
    kind = int(rng.integers(4))
    if kind == 0:
        return f"{value[:position]}{letter}{value[position + 1 :]}"
    if kind == 1:
        return f"{value[:position]}{value[position + 1 :]}"
    if kind == 2:
        return f"{value[:position]}{letter}{value[position:]}"
    first, second = value[position], value[position + 1]
    return f"{value[:position]}{second}{first}{value[position + 2 :]}"


def digit_typo(value: str, rng: np.random.Generator) -> str:
    """Change one digit in a string to a different digit.

    Args:
        value: Text holding at least one digit.
        rng: Random generator.

    Returns:
        The altered text, or ``value`` unchanged if it has no digits.
    """
    positions = [i for i, char in enumerate(value) if char.isdigit()]
    if not positions:
        return value
    position = positions[int(rng.integers(len(positions)))]
    digit = str((int(value[position]) + int(rng.integers(1, 10))) % 10)
    return f"{value[:position]}{digit}{value[position + 1 :]}"


def shortened(first_name: str, rng: np.random.Generator) -> str:
    """A common nickname if one is known, otherwise a short form of the name.

    Args:
        first_name: The full first name.
        rng: Random generator.

    Returns:
        The shorter name, or ``first_name`` if it is too short to shorten.
    """
    if first_name in NICKNAMES:
        return NICKNAMES[first_name]
    if len(first_name) < 5:
        return first_name
    return first_name[: int(rng.integers(3, 5))]


def nhs_digit_typo(number: str, rng: np.random.Generator) -> str:
    """Change one digit after the 999 prefix, which keeps the number in test range.

    A single changed digit always fails the modulus 11 check, so the result is
    never a valid number either.

    Args:
        number: A ten-digit NHS-style number.
        rng: Random generator.

    Returns:
        The altered number.
    """
    return f"{number[:3]}{digit_typo(number[3:], rng)}"


def swap_day_month(date: dt.date) -> dt.date | None:
    """The date with day and month exchanged, or ``None`` if that is impossible."""
    if date.day > 12 or date.day == date.month:
        return None
    try:
        return date.replace(month=date.day, day=date.month)
    except ValueError:
        return None


def date_typo(
    date: dt.date, reference: dt.date, rng: np.random.Generator
) -> dt.date | None:
    """A valid, different date, not after ``reference``, with one digit changed.

    Args:
        date: Original date.
        reference: Latest date allowed.
        rng: Random generator.

    Returns:
        The altered date, or ``None`` if ten attempts found no valid date.
    """
    for _ in range(10):
        text = digit_typo(date.strftime("%Y%m%d"), rng)
        try:
            altered = dt.datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            continue
        if altered != date and altered <= reference and altered.year >= 1900:
            return altered
    return None


def _donor(
    person: Mapping[str, Any],
    donors: Sequence[Mapping[str, Any]],
    rng: np.random.Generator,
) -> Mapping[str, Any]:
    """Another person, used for house moves and wrongly recorded numbers."""
    for _ in range(10):
        donor = donors[int(rng.integers(len(donors)))]
        if donor["person_id"] != person["person_id"]:
            return donor
    raise ValueError("Need at least two people to choose a different person")


def corrupt(
    person: Mapping[str, Any],
    rates: Mapping[str, float],
    donors: Sequence[Mapping[str, Any]],
    reference: dt.date,
    rng: np.random.Generator,
) -> tuple[dict[str, Any], list[str]]:
    """One source system's imperfect copy of a person.

    Args:
        person: The person's true details.
        rates: Probability of each error, by name.
        donors: All people, as the source of other people's details.
        reference: Latest possible date of birth.
        rng: Random generator.

    Returns:
        The record's fields and the names of the errors actually applied.
    """
    record = dict(person)
    errors: list[str] = []

    def hit(name: str) -> bool:
        return bool(rng.random() < rates[name])

    def apply(name: str, field: str, value: Any) -> None:
        if value != record[field]:
            record[field] = value
            errors.append(name)

    first = record["first_name"]
    if hit("first_name_nickname"):
        apply("first_name_nickname", "first_name", shortened(first, rng))
    if hit("first_name_typo"):
        apply("first_name_typo", "first_name", typo(record["first_name"], rng))
    if hit("first_name_initial"):
        apply("first_name_initial", "first_name", record["first_name"][0])

    if hit("surname_maiden") and person.get("maiden_name"):
        apply("surname_maiden", "surname", person["maiden_name"])
    if hit("surname_typo"):
        apply("surname_typo", "surname", typo(record["surname"], rng))
    if hit("names_swapped") and record["first_name"] != record["surname"]:
        record["first_name"], record["surname"] = (
            record["surname"],
            record["first_name"],
        )
        errors.append("names_swapped")

    if hit("dob_day_month_swap"):
        swapped = swap_day_month(record["date_of_birth"])
        if swapped is not None:
            apply("dob_day_month_swap", "date_of_birth", swapped)
    if hit("dob_typo"):
        altered = date_typo(record["date_of_birth"], reference, rng)
        if altered is not None:
            apply("dob_typo", "date_of_birth", altered)
    if hit("dob_missing"):
        apply("dob_missing", "date_of_birth", None)

    if hit("sex_missing"):
        apply("sex_missing", "sex", None)
    elif hit("sex_wrong"):
        apply("sex_wrong", "sex", "M" if record["sex"] == "F" else "F")

    if hit("moved_address"):
        other = _donor(person, donors, rng)
        for field in ("address", "city", "postcode"):
            record[field] = other[field]
        errors.append("moved_address")
    if hit("address_typo"):
        apply("address_typo", "address", typo(record["address"], rng))
    if hit("address_missing"):
        apply("address_missing", "address", None)
    if hit("postcode_typo") and record["postcode"]:
        apply("postcode_typo", "postcode", digit_typo(record["postcode"], rng))
    if hit("postcode_missing"):
        apply("postcode_missing", "postcode", None)

    if hit("nhs_digit_typo"):
        apply("nhs_digit_typo", "nhs_number", nhs_digit_typo(record["nhs_number"], rng))
    elif hit("nhs_wrong_person"):
        other = _donor(person, donors, rng)
        apply("nhs_wrong_person", "nhs_number", other["nhs_number"])

    return record, errors

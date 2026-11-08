# Data

All data here is **synthetic**. Nothing is committed (see `.gitignore`). Synthea output is kept outside the repo in `~/synthea`. `scripts/generate_populations.sh` generates the train, tune and test populations in the background and can be re-run after an interruption, and `make sources POP=<population>` rebuilds everything else.

## Provenance and licences

| Dataset | Source (URL) | Licence | Retrieved | Contains personal data? | Notes |
|---|---|---|---|---|---|
| Synthea synthetic patients | <https://github.com/synthetichealth/synthea> | Apache-2.0 (software) | 2026-11-08 | No: fully synthetic | Jar SHA-256 `20098ec70c24c715ea874b19140983634711cc4986196105b5b0a9ca72a4b644` (`master-branch-latest` release). Run with seed, clinician seed and reference date 2026-11-01. |

## Simulated source systems
`make sources` copies each person into up to three systems (hospital, GP, laboratory), each with its own fields and date format, and injects errors at three levels. Rates are in `configs/default.yaml`. They are **illustrative choices, not estimates of real-world error**.

- **Which person each record belongs to is kept apart,** in `data/truth/`, and is used only for evaluation.
- **NHS-style numbers** are generated only from the 999 range, with a valid modulus 11 check digit. That range is described as reserved for testing and never issued, in sources such as the [NHS number page](https://en.wikipedia.com/wiki/NHS_number) and the [`nhs-number` library](https://docs.rs/nhs-number); NHS Digital's own guidance could not be read directly. Injected digit errors change only digits after the prefix, so every number stays in that range.
- **Limitations:** names and addresses are American. About a quarter of Synthea's people have the placeholder ZIP `00000`, which is treated as missing. Synthea's names are unusually varied, and a realised error rate can sit below its configured rate when the error is not always possible: a day-month swap needs a day of 12 or less, for example.

## Folders
- `raw/` – untouched source files, never edited by hand
- `external/` – reference data (lookups, boundaries)
- `processed/sources/` – the simulated source files; always reproducible
- `truth/` – which person each record belongs to; for evaluation only

## Data protection
Only public, synthetic or properly licensed data is used. No real patient, client or employer data. Where a dataset relates to people, note the lawful basis or anonymisation status and any UK GDPR considerations.

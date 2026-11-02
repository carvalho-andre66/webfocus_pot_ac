# paradigm-webfocus-looker

Paradigm migration tool: WebFOCUS to Looker (BigQuery). CLI-first pipeline of numbered agents with state in MariaDB.

## Pipeline

| # | Path | Role |
|---|------|------|
| 0 | `0_extraction/` | Pull WebFOCUS content (file exports and REST) into staging |
| 1 | `1_rationalization/` | Retire / exclude / consolidate / rebuild / migrate |
| 2 | `2_assessment/` | Complexity scoring and effort estimates |
| 3 | `3_configuration/` | Looker connections, users, groups, roles |
| 4 | `4_transpilation/` | WebFOCUS logic to LookML |
| 5 | `5_content_generation/` | Reports to Looks and dashboards |
| 6 | `6_validation/` | Parity and LookML integrity checks |

Run an agent as a script:

```bash
uv run python 0_extraction/main.py
```

## Setup

```bash
uv sync
cp .env.example .env
uv run pytest
uv run ruff check .
```

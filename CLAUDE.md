# lakehouse-to-pg

dbt (DuckDB) bronze/silver/gold lakehouse, then `gold2psql` promotes gold tables to PostgreSQL
from one YAML config. Everything runs locally and in CI at zero cloud cost.

## Rules

- **Clean room:** 100% synthetic data and generic names. Never read, copy or reference employer
  repos, names, ticket IDs or schemas.
- Do not provision paid AWS resources. The `athena` target is documented only (ADR 0001).

## Commands

| Command | What it does |
|---------|--------------|
| `make run` | Everything: start containers, `dbt seed` + `build` + `test`, then `gold2psql` sync |
| `make up` / `make down` | Start / destroy Postgres (5433) and RabbitMQ (5672) |
| `make build` / `make test` | dbt only (DuckDB file in `.data/`) |
| `make sync` | gold -> Postgres using `gold2psql/config/pipeline_config.yml` |
| `make pytest` | gold2psql unit + integration tests (needs `make up`) |
| `make data` | Regenerate seed CSVs (seeded RNG, reproducible) |

## Layout

- `dbt/models/{silver,dimensions,gold}`, `dbt/macros`, `dbt/seeds` (seeds load into schema `bronze`)
- `gold2psql/src/gold2psql`: `config.py` (validation), `sync.py`, `masking.py`, `events.py`, `cli.py`
- `docs/adr`, `docs/runbooks`, `skills/add-gold-table-sync`

## Conventions and gotchas

- Adding a gold table: follow `skills/add-gold-table-sync/SKILL.md`.
- dbt generic-test args go under `arguments:`. Column-level `expression_is_true` gets the column
  name prepended automatically.
- SQL in `gold2psql` is composed with `psycopg.sql`; identifiers are validated in `config.py`.
  Keep new SQL parameterised or composed, never f-strings. The `_exec` helper carries the only
  `nosemgrep` suppression for the false-positive `.execute(variable)` rule.
- Integration tests skip when Postgres/RabbitMQ are unreachable. CI runs `make up` first so they
  cannot skip silently there.
- Masking is on everywhere except `GOLD2PSQL_ENV=prod`.
- Secrets: none in the repo. First run: `cp .env.example .env` (git-ignored; never commit it).
  `gold2psql`, pytest and `docker compose` read it, and real env vars win over it.
- `GOLD2PSQL_DSN` is required, `GOLD2PSQL_AMQP_URL` when a table has `post_sync_event`; in
  deployment inject them as real env vars.
- `dim_date` ends 2027-12-31; extend the `date_spine` end date before data goes past it.

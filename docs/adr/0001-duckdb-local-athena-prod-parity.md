# 0001. DuckDB locally, Athena for production parity

Status: accepted

## Context

The production shape for this lakehouse is S3 + Glue + Iceberg queried through Athena. Running
that for a portfolio demo costs money, needs credentials in CI, and makes every push slow. The
dbt project still has to be the same project that would run in production.

## Decision

- One dbt project, two targets in `dbt/profiles.yml`:
  - `duckdev` (DuckDB file in `.data/`) runs locally and in CI. It executes the whole pipeline.
  - `athena` is documented and configured but never run here.
- Bronze is dbt seeds loaded into a `bronze` schema and declared as sources, so silver models
  read `source()` exactly as they would read real raw tables.
- Where SQL differs between engines, use `adapter.dispatch` (see `format_date`: `strftime` on
  DuckDB, `date_format` on Athena).
- Gold models carry `+table_type: iceberg`. DuckDB ignores it; Athena needs Iceberg for
  incremental `merge`.
- `generate_schema_name` is overridden so schemas are plain `bronze` / `silver` / `gold` on every
  target.

## Consequences

- Zero cloud cost, fast CI, and the full pipeline (including Postgres sync) is exercised on every push.
- **Parity is not proven.** Several models use DuckDB syntax that Trino/Athena does not accept
  (`count(*) filter (where ...)`, `regexp_replace(..., 'g')`, `extract(isodow ...)`, the `~` regex
  operator in tests). Only `format_date` is dispatched so far. Treat the Athena target as a
  starting point, not a tested path.
- To close the gap: dispatch each engine-specific expression as it is found, and run a one-off
  `--target athena` smoke test against a throwaway Glue database before claiming production use.

## Alternatives considered

- Athena in CI: real parity, but paid, slow, and needs cloud secrets in a public repo.
- Postgres as the local engine: no Iceberg or Athena-style SQL, so it is no closer to production
  than DuckDB and loses the single-file, zero-service setup.

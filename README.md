# lakehouse-to-pg

A local lakehouse (dbt + DuckDB, bronze -> silver -> gold) and a config-driven sync that promotes
gold tables to PostgreSQL. All data is synthetic.

```
cp .env.example .env   # local-dev credentials; git-ignored
make run     # containers up, dbt seed -> build -> test, then gold -> Postgres sync
make pytest  # gold2psql unit + integration tests
```

Requires `uv`, `docker` and `make`.

- **dbt:** `dbt/`. DuckDB runs locally and in CI; an `athena` target is documented for S3/Glue/Iceberg
  ([ADR 0001](docs/adr/0001-duckdb-local-athena-prod-parity.md)).
- **Sync:** `gold2psql/`. One YAML file declares each table's key, full-refresh or watermark mode,
  non-prod masking, SQL hooks and a RabbitMQ event
  ([ADR 0002](docs/adr/0002-config-driven-gold-to-postgres-promotion.md)).
- **Operations:** [watermark drift runbook](docs/runbooks/sync-watermark-drift.md).

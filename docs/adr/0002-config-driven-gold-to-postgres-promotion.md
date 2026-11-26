# 0002. Config-driven gold -> PostgreSQL promotion

Status: accepted

## Context

Gold tables must be served from PostgreSQL. Each table needs the same handling (create, load,
mask outside prod, notify), with a few per-table differences. Hand-written sync code per table
would drift and is hard to review.

## Decision

`gold2psql` reads one file, `gold2psql/config/pipeline_config.yml`, and syncs the listed tables.

- **Two modes, exactly one per table.** `full_refresh: true` truncates and reloads, so source
  deletes carry over. `watermark_column` upserts rows with `watermark >= max(target watermark)`.
  `>=` (not `>`) means rows sharing the maximum are never missed; the upsert makes re-reading the
  boundary rows harmless. Syncs are idempotent.
- **One transaction per table.** Create-if-missing, load, and `post_sync_sql` hooks commit or roll
  back together (so hooks cannot use `VACUUM`).
- **Masking is fail-safe.** It applies in every environment except exactly `prod`. Strategies:
  `sequential`, `hash`, `null`; primary key and watermark columns cannot be masked.
- **Events after the commit.** `post_sync_event` publishes to RabbitMQ with a confirm, retrying
  `retries` times. If it still fails the CLI exits 3 and later tables are skipped; the data is
  already committed and re-running is safe.
- **Config is a trust boundary.** Identifiers are validated against `^[A-Za-z_][A-Za-z0-9_]*$` and
  composed with `psycopg.sql`. Hook SQL is operator-authored, like a dbt model.

## Consequences

- Adding a table is a config entry plus a dbt model (see `skills/add-gold-table-sync/SKILL.md`).
- **Watermark mode never propagates deletes or schema changes.** Rows deleted in gold stay in
  Postgres until a full refresh, and new gold columns fail the insert until the target is altered.
  See `docs/runbooks/sync-watermark-drift.md`.
- The source table is read fully into memory per sync (fine for gold-sized tables).
- Masking by `hash` is unsalted pseudonymisation, not anonymisation.

## Alternatives considered

- dbt post-hooks / a dbt Postgres target: couples serving to the lakehouse engine and has no
  watermark, masking or notification model.
- Postgres foreign data wrapper over DuckDB: no masking step and no event hook, and adds a
  moving part to the serving database.
- Per-table Python jobs: flexible, but the duplication this decision exists to avoid.

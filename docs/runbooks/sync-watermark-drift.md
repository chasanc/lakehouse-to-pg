# Runbook: sync watermark lag and row-count drift

Applies to tables in `gold2psql/config/pipeline_config.yml` using `watermark_column`
(`fct_lead_funnel`, `fct_orders`). Full-refresh tables mirror the source on every run, so they
cannot drift between runs.

## Severity

| Tier | Condition | Action |
|------|-----------|--------|
| **Page** | The sync job has failed or not run for 2 consecutive scheduled runs, **or** a `gold_sync_events` event failed after retries (CLI exit code 3) on a table consumers depend on, **or** a masked column is found unmasked outside `prod`. | Respond immediately. Start at "Triage". |
| **Ticket** | Watermark lag is above 1 run interval but the job is succeeding, **or** Postgres has *more* rows than gold (deleted source rows), **or** schema drift (new gold column). | Fix within the working week. |

Thresholds are illustrative for this demo; tune them to the real schedule.

## Triage

1. Did the last run succeed? `make sync` prints one line per table and exits non-zero on failure
   (2 = config/validation error, 3 = event failed *after* the data committed).
2. Is gold itself fresh? A stale source looks like sync lag. Run `make run`'s dbt stage first.
3. Run the diagnostics below, then pick the matching fix.

## Diagnostics

Source (DuckDB, read-only: `duckdb -readonly .data/lakehouse.duckdb`):

```sql
select count(*) as n, max(updated_at) as max_wm from gold.fct_orders;
```

Target (PostgreSQL):

```sql
select count(*) as n, max(updated_at) as max_wm from public.fct_orders;
```

Lag is `source max_wm - target max_wm`. Row drift is `source n - target n`.

Rows that exist in the target but not the source (deleted upstream): export the source primary
keys to a table in Postgres (`orders_source_keys`), then:

```sql
select o.order_id from public.fct_orders o
left join orders_source_keys k using (order_id)
where k.order_id is null;
```

Last sync activity per table:

```sql
select relname, n_tup_ins, n_tup_upd, last_analyze
from pg_stat_user_tables where schemaname = 'public' order by relname;
```

## Fixes

| Finding | Cause | Fix |
|---------|-------|-----|
| Target max watermark **behind** source, job succeeding | Source rows updated without moving `updated_at`, or the run did not execute | Fix the upstream model so `updated_at` moves on change; re-run `make sync`. |
| Target count **above** source | Rows deleted in gold; watermark mode never deletes | Run a one-off full reload: temporarily switch the table to `full_refresh: true`, run `uv run gold2psql --table <name>`, switch back. |
| Target count **below** source and lag is 0 | A row's watermark is older than the target maximum (late-arriving data) | One-off full reload as above, then make the model's watermark reflect ingestion time. |
| Insert fails with a missing column | New gold column; target table is created once | `alter table` the target to add the column, then re-run. |
| Exit code 3 | Broker unreachable after retries | Data is committed. Restore RabbitMQ, re-run `make sync` (idempotent) to resend. |
| Masked column holds real values | `GOLD2PSQL_ENV=prod` set in a non-prod environment | Unset it, truncate the table, re-sync, and treat the exposure as an incident. |

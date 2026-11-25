---
name: add-gold-table-sync
description: Add a dbt gold model and promote it to PostgreSQL through gold2psql. Use when asked to add, expose or sync a new gold table, fact or dimension in this repo.
---

# Add a gold table and its Postgres sync

Work through these in order. Run `make run` at the end; do not report done until it passes.

1. **Decide the grain** in one sentence (for example "one row per order"). Put it as a comment at
   the top of the model.
2. **Silver first.** If the entity has no `stg_*` model, add one in `dbt/models/silver/`: dedupe
   with `row_number()` on the key, cast types, rename to business-friendly names. Declare the raw
   table in `dbt/models/bronze/sources.yml`; add the seed to `dbt/seeds/` (synthetic data only,
   extend `scripts/gen_synthetic_data.py`, never hand-edit generated CSVs).
3. **Gold model** in `dbt/models/gold/` (`fct_*`) or `dbt/models/dimensions/` (`dim_*`).
   - Facts: `table`, or `incremental` with `unique_key` and `incremental_strategy='merge'` plus an
     `updated_at` filter inside `{% if is_incremental() %}`.
   - Use `join_date_dimension` / `format_date` rather than re-implementing date logic.
4. **Tests** in the matching `_gold.yml` / `_silver.yml`: `not_null` + `unique` on the key,
   `relationships` for every foreign key, and an `accepted_range` / `accepted_values` where it
   applies. Put generic-test args under `arguments:`.
5. **Pick the sync mode** and add an entry to `gold2psql/config/pipeline_config.yml`:
   - `full_refresh: true` for small tables or anything whose rows can be deleted upstream.
   - `watermark_column: <col>` only if the column reliably moves forward on every change.
     Deletes will not propagate (see `docs/runbooks/sync-watermark-drift.md`).
   - `primary_key` is required; `batch_size` is optional.
6. **PII?** For each text column holding personal data add `masking: {col: sequential|hash|null}`.
   `sequential` needs a single integer primary key. Primary key and watermark columns cannot be masked.
7. **Optional** `post_sync_sql` (runs in the sync transaction, `{table}` = target) and
   `post_sync_event` (`queue`, `retries`).
8. **Verify:** `make run`, then `make pytest`. Confirm the table's row count in the sync output
   matches the gold model, and a second `make sync` re-reads only boundary rows for watermark tables.
9. Add or extend a test in `gold2psql/tests/` only if you used a new config feature.

Never read or copy from any employer repository; data and names stay synthetic.

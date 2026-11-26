import re

import duckdb
import psycopg
from psycopg import sql

from gold2psql.config import Config, TableConfig
from gold2psql.events import publish, send_event
from gold2psql.masking import build_masker

_PG_TYPES = {
    "BOOLEAN": "boolean",
    "TINYINT": "smallint",
    "SMALLINT": "smallint",
    "INTEGER": "integer",
    "BIGINT": "bigint",
    "FLOAT": "real",
    "DOUBLE": "double precision",
    "VARCHAR": "text",
    "DATE": "date",
    "TIME": "time",
    "TIMESTAMP": "timestamp",
    "TIMESTAMP WITH TIME ZONE": "timestamptz",
}
_DECIMAL = re.compile(r"^DECIMAL\((\d+),\s*(\d+)\)$")


def pg_type(duck_type: str) -> str:
    if m := _DECIMAL.match(duck_type):
        return f"numeric({m[1]},{m[2]})"
    try:
        return _PG_TYPES[duck_type]
    except KeyError:
        raise ValueError(f"unsupported DuckDB type {duck_type!r}") from None


def _exec(pg: psycopg.Connection, query: sql.Composable) -> psycopg.Cursor:
    # Only ever called with psycopg.sql compositions (identifiers quoted by sql.Identifier, no
    # interpolated values), which is the injection-safe API; the generic rule can't tell.
    return pg.execute(query)  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query


def sync_table(src: duckdb.DuckDBPyConnection, pg: psycopg.Connection, source_schema: str,
               target_schema: str, t: TableConfig, mask: bool = True) -> int:
    """Copy one gold table into Postgres in a single transaction; returns rows written.

    The table's `post_sync_sql` hooks run in the same transaction (so no VACUUM), after the
    rows are written; `{table}` in a hook is the quoted target table. `mask` defaults to on.

    shortcut: target table is created from the source schema once; later column changes in
    gold are not migrated (inserts fail loudly), upgrade when gold schemas start evolving.
    """
    cols = src.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema = ? and table_name = ? order by ordinal_position",
        [source_schema, t.name],
    ).fetchall()
    names = [c for c, _ in cols]
    if not names:
        raise ValueError(f"{t.name}: not found in source schema {source_schema}")
    missing = [c for c in (*t.primary_key, t.watermark_column) if c and c not in names]
    if missing:
        raise ValueError(f"{t.name}: columns {missing} not found in {source_schema}.{t.name}")

    masker = build_masker(names, dict(cols), t.primary_key, t.masking) if mask else None

    target = sql.Identifier(target_schema, t.name)
    pk =sql.SQL(", ").join(map(sql.Identifier, t.primary_key))
    non_pk = [c for c in names if c not in t.primary_key]
    conflict = (
        sql.SQL("do update set ") + sql.SQL(", ").join(
            sql.SQL("{c} = excluded.{c}").format(c=sql.Identifier(c)) for c in non_pk)
        if non_pk else sql.SQL("do nothing")
    )
    insert = sql.SQL("insert into {} ({}) values ({}) on conflict ({}) {}").format(
        target,
        sql.SQL(", ").join(map(sql.Identifier, names)),
        sql.SQL(", ").join(sql.Placeholder() for _ in names),
        pk,
        conflict,
    )

    create_schema = sql.SQL("create schema if not exists {}").format(sql.Identifier(target_schema))
    create_table = sql.SQL("create table if not exists {} ({}, primary key ({}))").format(
        target,
        sql.SQL(", ").join(
            sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(pg_type(ty))) for c, ty in cols),
        pk,
    )

    with pg.transaction():
        _exec(pg, create_schema)
        _exec(pg, create_table)

        rel = src.table(f"{source_schema}.{t.name}")  # names validated against IDENT in config
        if t.full_refresh:
            _exec(pg, sql.SQL("truncate {}").format(target))
        else:
            # >= (not >) so rows sharing the max watermark are never missed; upsert makes
            # re-reading the boundary rows harmless.
            max_wm = sql.SQL("select max({}) from {}").format(sql.Identifier(t.watermark_column), target)
            watermark = _exec(pg, max_wm).fetchone()[0]
            if watermark is not None:
                rel = rel.filter(duckdb.ColumnExpression(t.watermark_column)
                                 >= duckdb.ConstantExpression(watermark))

        # shortcut: the source table is read fully into memory, then written in batches;
        # upgrade to a streaming arrow reader if a gold table outgrows RAM.
        data = rel.fetchall()
        if masker:
            data = [masker(row) for row in data]
        with pg.cursor() as pgcur:
            for i in range(0, len(data), t.batch_size):
                pgcur.executemany(insert, data[i:i + t.batch_size])

        # Hook SQL is operator-authored config, like a dbt model; {table} is the only substitution.
        for stmt in t.post_sync_sql:
            _exec(pg, sql.SQL(stmt).format(table=target))
    return len(data)


def sync_all(cfg: Config, only: set[str] | None = None, publisher=publish) -> dict[str, int]:
    """Sync tables in config order. A failed event raises EventError *after* that table's data
    committed; later tables are skipped, and re-running is safe (syncs are idempotent)."""
    unknown = (only or set()) - {t.name for t in cfg.tables}
    if unknown:
        raise ValueError(f"tables not in config: {sorted(unknown)}")
    results = {}
    src = duckdb.connect(str(cfg.duckdb_path), read_only=True)
    try:
        with psycopg.connect(cfg.dsn, autocommit=True) as pg:
            for t in cfg.tables:
                if only and t.name not in only:
                    continue
                results[t.name] = sync_table(src, pg, cfg.source_schema, cfg.target_schema, t,
                                             mask=cfg.mask)
                if ev := t.post_sync_event:
                    send_event(publisher, cfg.amqp_url, ev.queue,
                               {"table": t.name, "rows": results[t.name], "environment": cfg.environment},
                               ev.retries, ev.retry_delay_seconds)
    finally:
        src.close()
    return results

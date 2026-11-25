import json
import os
import uuid
from datetime import datetime
from decimal import Decimal

import duckdb
import pika
import psycopg
import pytest
from psycopg import sql

from gold2psql.config import Config, EventConfig, TableConfig
from gold2psql.events import EventError, publish
from gold2psql.sync import sync_all

pytestmark = pytest.mark.integration

DSN = os.environ.get("GOLD2PSQL_DSN", "postgresql://gold2psql:gold2psql@localhost:5433/serving")


def d(day):
    return datetime(2026, 1, day)


@pytest.fixture
def pg():
    try:
        conn = psycopg.connect(DSN, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as e:
        pytest.skip(f"Postgres not reachable (make up): {e}")
    with conn:
        yield conn


@pytest.fixture
def schema(pg):
    name = f"g2p_{uuid.uuid4().hex[:8]}"
    yield name
    drop = sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(name))
    pg.execute(drop)  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query


@pytest.fixture
def src(tmp_path):
    path = tmp_path / "src.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create schema gold")
    con.execute("create table gold.t (id integer, amount decimal(12,2), updated_at timestamp, note varchar)")
    con.executemany("insert into gold.t values (?, ?, ?, ?)", [
        (1, Decimal("10.00"), d(1), "a"),
        (2, Decimal("20.00"), d(2), "b"),
        (3, Decimal("30.00"), d(3), None),
    ])
    yield con
    con.close()


def run(tmp_path, schema, table):
    # The fixture connection holds the file open read-write, so sync a read-only copy.
    cfg = Config(tmp_path / "src.duckdb", "gold", DSN, schema, (table,))
    return sync_all(cfg)[table.name]


def rows(pg, schema):
    query = sql.SQL("select id, amount, note from {} order by id").format(sql.Identifier(schema, "t"))
    return pg.execute(query).fetchall()  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query


def test_full_refresh_mirrors_source_including_deletes(tmp_path, pg, schema, src):
    t = TableConfig("t", ("id",), batch_size=2, full_refresh=True)
    src.execute("checkpoint")
    src.close()
    assert run(tmp_path, schema, t) == 3
    assert rows(pg, schema) == [(1, Decimal("10.00"), "a"), (2, Decimal("20.00"), "b"), (3, Decimal("30.00"), None)]

    con = duckdb.connect(str(tmp_path / "src.duckdb"))
    con.execute("delete from gold.t where id = 2")
    con.close()
    assert run(tmp_path, schema, t) == 2
    assert [r[0] for r in rows(pg, schema)] == [1, 3]


def test_watermark_upserts_changed_and_new_rows_idempotently(tmp_path, pg, schema, src):
    t = TableConfig("t", ("id",), batch_size=2, watermark_column="updated_at")
    src.close()
    assert run(tmp_path, schema, t) == 3  # empty target: full load

    con = duckdb.connect(str(tmp_path / "src.duckdb"))
    con.execute("update gold.t set amount = 99.00, updated_at = '2026-01-05' where id = 2")
    con.execute("insert into gold.t values (4, 40.00, '2026-01-06', 'd')")
    con.close()

    # Rows at/after the old max watermark (day 3): id 3 (boundary), 2 (updated), 4 (new).
    assert run(tmp_path, schema, t) == 3
    assert rows(pg, schema) == [
        (1, Decimal("10.00"), "a"), (2, Decimal("99.00"), "b"),
        (3, Decimal("30.00"), None), (4, Decimal("40.00"), "d"),
    ]
    # Re-run: only the new boundary row is re-read; state is unchanged.
    assert run(tmp_path, schema, t) == 1
    assert len(rows(pg, schema)) == 4


def run_all(tmp_path, schema, table, publisher, environment="dev"):
    cfg = Config(tmp_path / "src.duckdb", "gold", DSN, schema, (table,),
                 environment=environment, amqp_url="amqp://stub")
    return sync_all(cfg, publisher=publisher)


def notes(pg, schema):
    query = sql.SQL("select note from {} order by id").format(sql.Identifier(schema, "t"))
    return [r[0] for r in pg.execute(query).fetchall()]  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query


def test_masking_hook_and_event(tmp_path, pg, schema, src):
    src.close()
    t = TableConfig("t", ("id",), full_refresh=True, masking={"note": "sequential"},
                    post_sync_sql=("comment on table {table} is 'synced'",),
                    post_sync_event=EventConfig("q", retries=1, retry_delay_seconds=0))
    sent = []
    assert run_all(tmp_path, schema, t, lambda url, queue, body: sent.append((url, queue, body))) == {"t": 3}

    assert notes(pg, schema) == ["note_1", "note_2", None]
    assert pg.execute("select obj_description(to_regclass(%s))", [f'"{schema}".t']).fetchone()[0] == "synced"
    (url, queue, body), = sent
    assert (url, queue) == ("amqp://stub", "q")
    assert json.loads(body) | {"sent_at": None} == {"table": "t", "rows": 3, "environment": "dev", "sent_at": None}


def test_prod_is_not_masked(tmp_path, pg, schema, src):
    src.close()
    t = TableConfig("t", ("id",), full_refresh=True, masking={"note": "sequential"})
    run_all(tmp_path, schema, t, publisher=None, environment="prod")
    assert notes(pg, schema) == ["a", "b", None]


def test_failed_hook_rolls_back_the_table(tmp_path, pg, schema, src):
    src.close()
    t = TableConfig("t", ("id",), full_refresh=True, post_sync_sql=("select * from does_not_exist",))
    with pytest.raises(psycopg.errors.UndefinedTable):
        run_all(tmp_path, schema, t, publisher=None)
    assert pg.execute("select to_regclass(%s)", [f'"{schema}".t']).fetchone()[0] is None


def test_event_failure_raises_after_data_committed(tmp_path, pg, schema, src):
    src.close()
    t = TableConfig("t", ("id",), full_refresh=True,
                    post_sync_event=EventConfig("q", retries=1, retry_delay_seconds=0))
    attempts = []

    def down(url, queue, body):
        attempts.append(1)
        raise ConnectionError("broker down")

    with pytest.raises(EventError, match="2 attempts"):
        run_all(tmp_path, schema, t, down)
    assert len(attempts) == 2 and len(rows(pg, schema)) == 3


def test_rabbitmq_publish_roundtrip():
    url = os.environ.get("GOLD2PSQL_AMQP_URL", "amqp://guest:guest@localhost:5672/")
    queue = f"g2p_test_{uuid.uuid4().hex[:8]}"
    try:
        publish(url, queue, b'{"table": "t"}')
    except Exception as e:  # pika raises several unrelated connection errors
        pytest.skip(f"RabbitMQ not reachable (make up): {e}")
    with pika.BlockingConnection(pika.URLParameters(url)) as conn:
        ch = conn.channel()
        _, props, body = ch.basic_get(queue, auto_ack=True)
        ch.queue_delete(queue)
    assert body == b'{"table": "t"}' and props.delivery_mode == 2


def test_missing_column_fails_without_touching_target(tmp_path, pg, schema, src):
    src.close()
    t = TableConfig("t", ("id",), watermark_column="nope")
    with pytest.raises(ValueError, match="nope"):
        run(tmp_path, schema, t)
    assert pg.execute("select count(*) from information_schema.schemata where schema_name = %s",
                      [schema]).fetchone()[0] == 0

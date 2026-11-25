import pytest
import yaml

from gold2psql.config import ConfigError, load_config
from gold2psql.sync import pg_type


def write_cfg(tmp_path, tables, **overrides):
    cfg = {
        "source": {"duckdb_path": "x.duckdb", "schema": "gold"},
        "target": {"dsn": "postgresql://u:p@h/db", "schema": "public"},
        "tables": tables,
    } | overrides
    path = tmp_path / "c.yml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def test_valid_config(tmp_path, monkeypatch):
    monkeypatch.delenv("GOLD2PSQL_DSN", raising=False)
    cfg = load_config(write_cfg(tmp_path, [
        {"name": "a", "primary_key": ["id"], "full_refresh": True},
        {"name": "b", "primary_key": ["id"], "watermark_column": "updated_at", "batch_size": 10},
    ]))
    assert [t.name for t in cfg.tables] == ["a", "b"]
    assert cfg.tables[0].batch_size == 1000 and cfg.tables[0].full_refresh
    assert cfg.tables[1].watermark_column == "updated_at" and cfg.tables[1].batch_size == 10


def test_dsn_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLD2PSQL_DSN", "postgresql://env/db")
    cfg = load_config(write_cfg(tmp_path, [{"name": "a", "primary_key": ["id"], "full_refresh": True}]))
    assert cfg.dsn == "postgresql://env/db"


@pytest.mark.parametrize("table", [
    {"name": "a", "full_refresh": True},                                              # no pk
    {"name": "a", "primary_key": [], "full_refresh": True},                           # empty pk
    {"name": "a", "primary_key": ["id"]},                                             # no mode
    {"name": "a", "primary_key": ["id"], "full_refresh": True, "watermark_column": "u"},  # both
    {"name": "a", "primary_key": ["id"], "full_refresh": True, "batch_size": 0},
    {"name": "a", "primary_key": ["id"], "full_refresh": True, "bogus": 1},           # unknown key
    {"name": "a", "primary_key": ["id"], "full_refresh": True, "masking": {"e": "rot13"}},
    {"name": "a", "primary_key": ["id"], "full_refresh": True, "masking": {"id": "hash"}},  # pk
    {"name": "a", "primary_key": ["id"], "full_refresh": True, "post_sync_sql": "analyze"},
    {"name": "a", "primary_key": ["id"], "full_refresh": True, "post_sync_event": {"retries": 1}},
    {"name": "a", "primary_key": ["id"], "full_refresh": True,
     "post_sync_event": {"queue": "q", "retries": -1}},
    {"name": "a; drop table x", "primary_key": ["id"], "full_refresh": True},
    {"name": "a", "primary_key": ["id\""], "full_refresh": True},
])
def test_invalid_table(tmp_path, table):
    with pytest.raises(ConfigError):
        load_config(write_cfg(tmp_path, [table]))


def test_optional_sections(tmp_path, monkeypatch):
    monkeypatch.delenv("GOLD2PSQL_ENV", raising=False)
    monkeypatch.delenv("GOLD2PSQL_AMQP_URL", raising=False)
    cfg = load_config(write_cfg(tmp_path, [{
        "name": "a", "primary_key": ["id"], "full_refresh": True,
        "masking": {"email": "sequential"}, "post_sync_sql": ["analyze {table}"],
        "post_sync_event": {"queue": "q"},
    }], events={"url": "amqp://x"}))
    t = cfg.tables[0]
    assert t.masking == {"email": "sequential"} and t.post_sync_sql == ("analyze {table}",)
    assert (t.post_sync_event.queue, t.post_sync_event.retries) == ("q", 3)
    assert cfg.environment == "dev" and cfg.mask and cfg.amqp_url == "amqp://x"


def test_event_needs_broker_url(tmp_path, monkeypatch):
    monkeypatch.delenv("GOLD2PSQL_AMQP_URL", raising=False)
    with pytest.raises(ConfigError, match="events.url"):
        load_config(write_cfg(tmp_path, [{"name": "a", "primary_key": ["id"], "full_refresh": True,
                                          "post_sync_event": {"queue": "q"}}]))


@pytest.mark.parametrize("env,masked", [("prod", False), ("dev", True), ("staging", True), ("PROD", True)])
def test_mask_everywhere_except_prod(tmp_path, monkeypatch, env, masked):
    monkeypatch.setenv("GOLD2PSQL_ENV", env)
    cfg = load_config(write_cfg(tmp_path, [{"name": "a", "primary_key": ["id"], "full_refresh": True}]))
    assert cfg.mask is masked


def test_duplicate_tables(tmp_path):
    t = {"name": "a", "primary_key": ["id"], "full_refresh": True}
    with pytest.raises(ConfigError):
        load_config(write_cfg(tmp_path, [t, t]))


def test_missing_section(tmp_path):
    path = tmp_path / "c.yml"
    path.write_text("tables: []\n")
    with pytest.raises(ConfigError):
        load_config(path)


@pytest.mark.parametrize("duck,pg", [
    ("INTEGER", "integer"), ("VARCHAR", "text"), ("DECIMAL(12,2)", "numeric(12,2)"),
    ("TIMESTAMP", "timestamp"), ("DATE", "date"), ("BOOLEAN", "boolean"),
])
def test_pg_type(duck, pg):
    assert pg_type(duck) == pg


def test_pg_type_unsupported():
    with pytest.raises(ValueError):
        pg_type("STRUCT(a INTEGER)")

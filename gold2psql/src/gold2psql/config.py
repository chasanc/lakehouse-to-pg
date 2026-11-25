import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from gold2psql.masking import STRATEGIES

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TABLE_KEYS = {"name", "primary_key", "batch_size", "full_refresh", "watermark_column",
              "masking", "post_sync_sql", "post_sync_event"}
EVENT_KEYS = {"queue", "retries", "retry_delay_seconds"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class EventConfig:
    queue: str
    retries: int = 3
    retry_delay_seconds: float = 1.0


@dataclass(frozen=True)
class TableConfig:
    name: str
    primary_key: tuple[str, ...]
    batch_size: int = 1000
    full_refresh: bool = False
    watermark_column: str | None = None
    masking: dict[str, str] = field(default_factory=dict)
    post_sync_sql: tuple[str, ...] = ()
    post_sync_event: EventConfig | None = None


@dataclass(frozen=True)
class Config:
    duckdb_path: Path
    source_schema: str
    dsn: str
    target_schema: str
    tables: tuple[TableConfig, ...]
    environment: str = "dev"
    amqp_url: str | None = None

    @property
    def mask(self) -> bool:
        # Fail-safe: anything that is not exactly "prod" gets masked.
        return self.environment != "prod"


def _ident(value, what: str) -> str:
    # Names end up in SQL, so the config is a trust boundary.
    if not isinstance(value, str) or not IDENT.match(value):
        raise ConfigError(f"{what}: {value!r} is not a valid identifier")
    return value


def _masking(name: str, raw, pk: tuple[str, ...], watermark: str | None) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ConfigError(f"{name}: masking must be a mapping of column -> strategy")
    out = {}
    for col, strategy in raw.items():
        _ident(col, f"{name}.masking")
        if strategy not in STRATEGIES:
            raise ConfigError(f"{name}.masking.{col}: strategy must be one of {sorted(STRATEGIES)}")
        if col in pk or col == watermark:
            raise ConfigError(f"{name}.masking.{col}: primary key / watermark columns cannot be masked")
        out[col] = strategy
    return out


def _event(name: str, raw) -> EventConfig:
    if not isinstance(raw, dict) or set(raw) - EVENT_KEYS or "queue" not in raw:
        raise ConfigError(f"{name}.post_sync_event: needs 'queue'; allowed keys {sorted(EVENT_KEYS)}")
    retries = raw.get("retries", 3)
    delay = raw.get("retry_delay_seconds", 1.0)
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        raise ConfigError(f"{name}.post_sync_event.retries must be an integer >= 0")
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or delay < 0:
        raise ConfigError(f"{name}.post_sync_event.retry_delay_seconds must be a number >= 0")
    queue = raw["queue"]
    if not isinstance(queue, str) or not queue:
        raise ConfigError(f"{name}.post_sync_event.queue must be a non-empty string")
    return EventConfig(queue, retries, float(delay))


def _table(raw) -> TableConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"table entry must be a mapping, got {raw!r}")
    name = _ident(raw.get("name"), "table name")
    unknown = set(raw) - TABLE_KEYS
    if unknown:
        raise ConfigError(f"{name}: unknown keys {sorted(unknown)}")
    pk = raw.get("primary_key")
    if not isinstance(pk, list) or not pk:
        raise ConfigError(f"{name}: primary_key must be a non-empty list")
    batch_size = raw.get("batch_size", 1000)
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
        raise ConfigError(f"{name}: batch_size must be a positive integer")
    full_refresh = raw.get("full_refresh", False)
    watermark = raw.get("watermark_column")
    if not isinstance(full_refresh, bool):
        raise ConfigError(f"{name}: full_refresh must be true or false")
    if full_refresh == (watermark is not None):
        raise ConfigError(f"{name}: set exactly one of full_refresh: true or watermark_column")
    pk_cols = tuple(_ident(c, f"{name}.primary_key") for c in pk)
    watermark = _ident(watermark, f"{name}.watermark_column") if watermark else None
    hooks = raw.get("post_sync_sql", [])
    if not isinstance(hooks, list) or not all(isinstance(h, str) and h.strip() for h in hooks):
        raise ConfigError(f"{name}.post_sync_sql must be a list of non-empty SQL strings")
    return TableConfig(
        name=name,
        primary_key=pk_cols,
        batch_size=batch_size,
        full_refresh=full_refresh,
        watermark_column=watermark,
        masking=_masking(name, raw["masking"], pk_cols, watermark) if "masking" in raw else {},
        post_sync_sql=tuple(hooks),
        post_sync_event=_event(name, raw["post_sync_event"]) if "post_sync_event" in raw else None,
    )


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text())
    try:
        source, target, tables = raw["source"], raw["target"], raw["tables"]
        duckdb_path, source_schema = source["duckdb_path"], source["schema"]
        dsn = os.environ.get("GOLD2PSQL_DSN") or target.get("dsn")
        target_schema = target.get("schema", "public")
    except (KeyError, TypeError, AttributeError) as e:
        raise ConfigError(f"missing or malformed config section: {e}") from e
    if not dsn:
        raise ConfigError("no target DSN: set GOLD2PSQL_DSN (see .env.example)")
    if not isinstance(tables, list) or not tables:
        raise ConfigError("tables must be a non-empty list")
    parsed = tuple(_table(t) for t in tables)
    names = [t.name for t in parsed]
    if len(set(names)) != len(names):
        raise ConfigError("duplicate table names")
    environment = os.environ.get("GOLD2PSQL_ENV") or raw.get("environment", "dev")
    if not isinstance(environment, str) or not environment:
        raise ConfigError("environment must be a non-empty string")
    amqp_url = os.environ.get("GOLD2PSQL_AMQP_URL") or (raw.get("events") or {}).get("url")
    if any(t.post_sync_event for t in parsed) and not amqp_url:
        raise ConfigError("post_sync_event is used but events.url / GOLD2PSQL_AMQP_URL is not set")
    return Config(
        duckdb_path=Path(duckdb_path),
        source_schema=_ident(source_schema, "source.schema"),
        dsn=dsn,
        target_schema=_ident(target_schema, "target.schema"),
        tables=parsed,
        environment=environment,
        amqp_url=amqp_url,
    )

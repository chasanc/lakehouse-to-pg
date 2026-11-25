import argparse
import sys

from gold2psql.config import ConfigError, load_config
from gold2psql.events import EventError
from gold2psql.sync import sync_all


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gold2psql", description="Promote gold tables to PostgreSQL")
    p.add_argument("--config", default="gold2psql/config/pipeline_config.yml")
    p.add_argument("--table", action="append", help="only sync this table (repeatable)")
    args = p.parse_args(argv)
    try:
        results = sync_all(load_config(args.config), set(args.table or []))
    except (ConfigError, ValueError) as e:
        print(f"gold2psql: {e}", file=sys.stderr)
        return 2
    except EventError as e:
        print(f"gold2psql: {e} (the table data was committed; re-run to resend)", file=sys.stderr)
        return 3
    for name, rows in results.items():
        print(f"{name}: {rows} rows")
    return 0

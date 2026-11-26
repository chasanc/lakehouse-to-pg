import argparse
import os
import sys
from pathlib import Path

from gold2psql.config import REPO_ROOT, ConfigError, load_config
from gold2psql.events import EventError
from gold2psql.sync import sync_all


def load_dotenv(path: str | Path = REPO_ROOT / ".env") -> None:
    """Fill os.environ from a .env file; variables already set (injected secrets) win."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        key, sep, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        if not sep or key.startswith("#"):
            continue
        value = value.strip()
        if value[:1] in "\"'" and value.endswith(value[:1]) and len(value) > 1:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()  # compose strips inline comments too
        os.environ.setdefault(key, value)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gold2psql", description="Promote gold tables to PostgreSQL")
    p.add_argument("--config", default=str(REPO_ROOT / "gold2psql/config/pipeline_config.yml"))
    p.add_argument("--table", action="append", help="only sync this table (repeatable)")
    args = p.parse_args(argv)
    load_dotenv()
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

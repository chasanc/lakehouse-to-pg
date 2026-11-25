import hashlib

STRATEGIES = {"sequential", "hash", "null"}


def _shape(column: str, token, original: str) -> str:
    # Keep email-looking values email-looking so downstream validation still passes.
    return f"{column}_{token}" + ("@example.com" if "@" in original else "")


def build_masker(names: list[str], types: dict[str, str], primary_key: tuple[str, ...],
                 masking: dict[str, str]):
    """Return a row -> row function applying `masking`, or None when nothing is masked.

    sequential: `<column>_<n>` where n is the row's integer primary key (stable and unique
                across incremental runs; needs a single integer-keyed table).
    hash:       `<column>_<first 12 hex of sha256(value)>`; same input, same output.
    null:       NULL.
    NULLs stay NULL. shortcut: hash is unsalted, so it pseudonymises low-entropy values
    (emails, phones) rather than anonymising them; add a salt before using it on real PII.
    """
    if not masking:
        return None
    missing = [c for c in masking if c not in names]
    if missing:
        raise ValueError(f"masking columns not found in source: {missing}")
    bad = [c for c, s in masking.items() if s != "null" and types[c] != "VARCHAR"]
    if bad:
        raise ValueError(f"sequential/hash masking needs VARCHAR columns, got non-text: {bad}")
    if "sequential" in masking.values() and len(primary_key) != 1:
        raise ValueError("sequential masking needs a single-column primary key")
    pk_idx = names.index(primary_key[0])
    plan = [(names.index(c), c, s) for c, s in masking.items()]

    def mask(row: tuple) -> tuple:
        out = list(row)
        for i, column, strategy in plan:
            value = row[i]
            if value is None or strategy == "null":
                out[i] = None
            elif strategy == "hash":
                out[i] = _shape(column, hashlib.sha256(str(value).encode()).hexdigest()[:12], value)
            else:
                n = row[pk_idx]
                if not isinstance(n, int) or isinstance(n, bool):
                    raise ValueError(f"sequential masking needs an integer primary key, got {n!r}")
                out[i] = _shape(column, n, value)
        return tuple(out)

    return mask

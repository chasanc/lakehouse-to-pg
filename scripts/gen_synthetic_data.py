"""Generate 100% synthetic, reproducible seed CSVs into dbt/seeds/."""
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

SEEDS = Path(__file__).resolve().parent.parent / "dbt" / "seeds"
rng = random.Random(42)

FIRST = ["Ava", "Noah", "Mia", "Liam", "Zoe", "Ethan", "Ivy", "Leo", "Nora", "Omar"]
LAST = ["Stone", "Reed", "Park", "Lopez", "Khan", "Meyer", "Silva", "Ito", "Frost", "Bell"]
STAGES = ["new", "contacted", "qualified", "won", "lost"]
N_USERS, N_LEADS, N_DUPES = 20, 200, 12


def name() -> str:
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def phone() -> str:
    # Fictional 555-01xx range, in deliberately messy formats; one format is invalid.
    d = f"415555{rng.randint(0, 99):04d}"
    fmt = rng.choice(["({}) {}-{}", "{}-{}-{}", "+1 {} {} {}", "{}{}{}", "001 {} {} {}", "bad"])
    if fmt == "bad":
        return "555-01"
    return fmt.format(d[:3], d[3:6], d[6:])


def write(fname: str, header: list[str], rows: list[list]) -> None:
    SEEDS.mkdir(parents=True, exist_ok=True)
    with open(SEEDS / fname, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


users = []
for uid in range(1, N_USERS + 1):
    is_mgr = uid <= 4
    users.append([uid, name(), "manager" if is_mgr else "agent", "" if is_mgr else rng.randint(1, 4)])
write("users.csv", ["user_id", "full_name", "role", "manager_id"], users)

base = datetime(2026, 1, 1)
leads = []
for lid in range(1, N_LEADS + 1):
    created = base + timedelta(days=rng.randint(0, 300), minutes=rng.randint(0, 1439))
    n = name()
    leads.append([
        lid, rng.randint(5, N_USERS), f"  {n} ", f"{n.replace(' ', '.').upper()}@example.com",
        phone(), rng.choice(STAGES), created.isoformat(sep=" "),
        (created + timedelta(days=rng.randint(0, 20))).isoformat(sep=" "),
    ])
# Duplicates: same lead_id re-delivered later with a newer stage; silver must keep the latest.
for row in rng.sample(leads, N_DUPES):
    dup = list(row)
    dup[5] = "won"
    dup[7] = (datetime.fromisoformat(row[7]) + timedelta(days=30)).isoformat(sep=" ")
    leads.append(dup)
write("crm_leads.csv",
      ["lead_id", "user_id", "full_name", "email", "phone_raw", "stage", "created_at", "updated_at"],
      leads)

# Calls: attached to original leads, made by the lead's owner. A few exact duplicate rows.
calls = []
for cid in range(1, 401):
    lead = rng.choice(leads[:N_LEADS])
    started = datetime.fromisoformat(lead[6]) + timedelta(days=rng.randint(0, 30), minutes=rng.randint(0, 600))
    calls.append([cid, lead[0], lead[1], started.isoformat(sep=" "), rng.randint(0, 1800),
                  rng.choice(["inbound", "outbound"]),
                  rng.choice(["answered", "voicemail", "no_answer"])])
calls += [list(c) for c in rng.sample(calls, 5)]
write("call_logs.csv",
      ["call_id", "lead_id", "user_id", "started_at", "duration_sec", "direction", "outcome"], calls)

# Orders: 1-2 per lead that ends up 'won' (latest row per lead_id wins).
latest = {}
for row in leads:
    if row[0] not in latest or row[7] > latest[row[0]][7]:
        latest[row[0]] = row
orders, oid = [], 1
for row in latest.values():
    if row[5] != "won":
        continue
    for _ in range(rng.randint(1, 2)):
        ordered = datetime.fromisoformat(row[7]) + timedelta(days=rng.randint(0, 30))
        orders.append([oid, row[0], f"{rng.uniform(50, 2000):.2f}", rng.choice(["USD", "EUR"]),
                       rng.choice(["paid", "paid", "pending", "refunded"]), ordered.isoformat(sep=" "),
                       (ordered + timedelta(days=rng.randint(0, 10))).isoformat(sep=" ")])
        oid += 1
write("orders.csv",
      ["order_id", "lead_id", "amount", "currency", "status", "ordered_at", "updated_at"], orders)
print(f"wrote {len(users)} users, {len(leads)} lead rows, {len(calls)} calls, {len(orders)} orders to {SEEDS}")

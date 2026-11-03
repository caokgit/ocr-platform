"""Acceptance B6, T4: how long each replayed save of one result took to reach silver, from its commit in live
(the event's source.ts_ms) to the commit of the first silver snapshot holding it (docs/specs/data-path.md#acceptance).

    arguments: env:result_id since_epoch_ms     e.g. stg:17 1793567000000
"""

import sys

sys.path.insert(0, "/opt/lab")
from common import CATALOG, session  # noqa: E402

target, since = sys.argv[1], int(sys.argv[2])
env, rid = target.split(":")
spark = session("lab-t4")
table = "request_ticket_result"
events = spark.sql(f"""SELECT lsn, source_ts_ms FROM {CATALOG}.bronze.{env}_odoo_{table}
    WHERE source_ts_ms >= {since} AND get_json_object(value, '$.after.id') = '{rid}' ORDER BY lsn""").collect()
snaps = spark.sql(f"""SELECT snapshot_id, unix_millis(committed_at) AS ms FROM {CATALOG}.silver.{table}.snapshots
    WHERE unix_millis(committed_at) >= {since} ORDER BY committed_at""").collect()
held = []
for s in snaps:
    r = spark.sql(f"SELECT _lsn FROM {CATALOG}.silver.{table} VERSION AS OF {s.snapshot_id} "
                  f"WHERE env = '{env}' AND id = {rid}").collect()
    held.append((s.ms, r[0]._lsn if r else None))
worst = 0.0
for n, e in enumerate(events, 1):
    first = next((ms for ms, lsn in held if lsn is not None and lsn >= e.lsn), None)
    if first is None:
        print(f"save {n}: lsn {e.lsn} never reached silver")
        worst = float("inf")
        continue
    sec = (first - e.source_ts_ms) / 1000
    worst = max(worst, sec)
    print(f"save {n}: committed in live at {e.source_ts_ms}, in silver {sec:.1f} s later")
print(f"T4 {target}: {len(events)} saves, the slowest {worst:.1f} s to silver "
      f"({'within' if worst <= 60 else 'OVER'} 60 s); {len(snaps)} silver snapshots in the window")
spark.stop()

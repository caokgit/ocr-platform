#!/usr/bin/env python3
"""Replay the lab's archive into live in event-time order, so Debezium sees the changes the client's databases saw.

    python3 replay.py init                       # live's tables (archive's, without history columns), lab_meta
    python3 replay.py fill [--speedup N]         # the whole history, paced (default: about 10 minutes)
    python3 replay.py slice dev:1 [--gap 30]     # one result's saves again, into a filled live (the T4 check)
    python3 replay.py verify                     # live equals archive, table by table (rows and content)

Spec: docs/specs/data-path.md#replay
Runs as a Job on the box (pipelines/replay/launch.py), or anywhere libpq's PGHOST, PGPORT, PGUSER and PGPASSWORD
reach the lab's Postgres as the role replayer (owner of live, reader of archive).
"""

import argparse
import datetime
import sys
import time
from collections import defaultdict

import psycopg
from psycopg import sql
from psycopg.types.string import TextLoader

ENVS = ("dev", "stg")
SVC_TABLES = ["document", "document_run", "document_page", "document_unit", "match_candidate",
              "element_record", "run_element", "run_stage"]
CHILDREN = SVC_TABLES[2:]          # written with their run's final row
ODOO_TABLES = ["ocr_element", "ocr_document_template", "ocr_element_prompt",
               "product_document", "ir_attachment", "request_ticket_result"]
# table -> (history column, the column each version fills); the history column is never written to live
HISTORY = {"request_ticket_result": ("result_history", "result"),
           "ocr_document_template": ("settings_history", "settings")}
PUBLISHED = ["published_version", "published_version_label", "published_at"]
# A run as it started (spec row 24): completion columns empty, NOT NULL columns at their in-progress value.
RUN_STARTED = {"status": "running", "completed_stage": "none", "current_stage": "none", "items_done": 0,
               "progress_percent": 0, "progress_sequence": 0, "progress_phase_ordinal": 0,
               "progress_phase_state_ordinal": 0, "progress_items_done": 0}
RUN_COMPLETION = ["completed_at", "duration_ms", "failed_at", "error_code", "error_detail", "page_count",
                  "items_total", "progress_items_total", "progress_updated_at", "lease_token", "lease_expires_at"]
UTC = datetime.timezone.utc
ORDER = {"doc_first": 0, "run_start": 1, "run_end": 2, "doc_final": 3, "version": 4, "row": 5}


def log(msg):
    print(f"{datetime.datetime.now(UTC):%H:%M:%S} {msg}", flush=True)


def connect(db):
    conn = psycopg.connect(dbname=db, autocommit=False)
    for t in ("json", "jsonb"):            # keep JSON as text: it goes back into Postgres unchanged
        conn.adapters.register_loader(t, TextLoader)
    return conn


def utc(ts):
    if ts is None:
        return None
    if isinstance(ts, str):
        ts = datetime.datetime.fromisoformat(ts)
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)   # Odoo stores UTC without a zone


def tables():
    for env in ENVS:
        for t in SVC_TABLES:
            yield f"{env}_svc", t
        for t in ODOO_TABLES:
            yield f"{env}_odoo", t


def columns(conn, schema, table):
    """[(name, type, notnull)] in order, and the primary key, from the catalog."""
    rows = conn.execute("""
        SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
               EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'p'
                       AND a.attnum = ANY (k.conkey))
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_attribute a ON a.attrelid = c.oid
        WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum""",
        (schema, table)).fetchall()
    if not rows:
        sys.exit(f"{schema}.{table}: not found")
    pk = [r[0] for r in rows if r[3]]
    if pk != ["id"]:
        sys.exit(f"{schema}.{table}: primary key {pk}, the replay expects id")
    return [(r[0], r[1], r[2]) for r in rows]


class Table:
    """What live holds of one archive table: its columns (history left out), and how to read and upsert rows."""

    def __init__(self, archive, schema, table):
        self.schema, self.table = schema, table
        hist = HISTORY.get(table, (None,))[0]
        self.cols = [c for c in columns(archive, schema, table) if c[0] != hist]
        self.names = [c[0] for c in self.cols]
        ident = sql.Identifier(schema, table)
        self.select = sql.SQL("SELECT {} FROM {}").format(
            sql.SQL(", ").join(sql.Identifier(n) for n in self.names), ident)
        self.upsert = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT (id) DO UPDATE SET {}").format(
            ident, sql.SQL(", ").join(sql.Identifier(n) for n in self.names),
            sql.SQL(", ").join(sql.SQL("%s::" + typ) for _, typ, _ in self.cols),
            sql.SQL(", ").join(sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(n))
                               for n in self.names if n != "id"))

    def by_ids(self, archive, ids):
        q = self.select + sql.SQL(" WHERE id = ANY(%s) ORDER BY id")
        return [dict(zip(self.names, r)) for r in archive.execute(q, (list(ids),))]

    def by_run(self, archive, run_id):
        q = self.select + sql.SQL(" WHERE run_id = %s ORDER BY id")
        return [dict(zip(self.names, r)) for r in archive.execute(q, (run_id,))]

    def write(self, live, rows):
        if rows:
            with live.cursor() as cur:
                cur.executemany(self.upsert, [[r[n] for n in self.names] for r in rows])
        return len(rows)


def ddl(t):
    body = [sql.SQL("{} {}{}").format(sql.Identifier(n), sql.SQL(typ), sql.SQL(" NOT NULL" if nn else ""))
            for n, typ, nn in t.cols] + [sql.SQL("PRIMARY KEY (id)")]
    return sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(
        sql.Identifier(t.schema, t.table), sql.SQL(", ").join(body))


def init(archive, live):
    for schema, table in tables():
        live.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        live.execute(ddl(Table(archive, schema, table)))
    live.execute("CREATE SCHEMA IF NOT EXISTS lab_meta")
    live.execute("CREATE TABLE IF NOT EXISTS lab_meta.heartbeat (id int PRIMARY KEY, ts timestamptz NOT NULL)")
    for schema in sorted({s for s, _ in tables()}):
        live.execute(sql.SQL("GRANT USAGE ON SCHEMA {0} TO debezium; GRANT SELECT ON ALL TABLES IN SCHEMA {0} "
                             "TO debezium").format(sql.Identifier(schema)))
    live.execute("GRANT USAGE ON SCHEMA lab_meta TO debezium; "
                 "GRANT SELECT, INSERT, UPDATE ON lab_meta.heartbeat TO debezium")
    live.commit()
    log(f"live: {len(list(tables()))} tables and lab_meta.heartbeat ready, debezium granted read access")


def live_rows(live):
    q = sql.SQL(" + ").join(sql.SQL("(SELECT count(*) FROM {})").format(sql.Identifier(s, t)) for s, t in tables())
    return live.execute(sql.SQL("SELECT ") + q).fetchone()[0]


def history(archive, schema, table):
    """{id: [(time, index into the stored array)]}, oldest first (the arrays are stored newest first)."""
    hcol = HISTORY[table][0]
    q = sql.SQL("SELECT t.id, h.e->>'create_date', h.o - 1 FROM {} t, jsonb_array_elements(CASE WHEN "
                "jsonb_typeof(t.{c}) = 'array' THEN t.{c} ELSE '[]' END) WITH ORDINALITY h(e, o)").format(
        sql.Identifier(schema, table), c=sql.Identifier(hcol))
    out = defaultdict(list)
    for rid, ts, idx in archive.execute(q):
        out[rid].append((utc(ts), idx))
    return {k: sorted(v) for k, v in out.items()}


def events(archive):
    """Every write of the replay as (time, order, kind, schema, table, id, version index), unsorted."""
    ev = []
    for env in ENVS:
        s = f"{env}_svc"
        runs = archive.execute(sql.SQL("SELECT id, document_id, started_at, completed_at FROM {}").format(
            sql.Identifier(s, "document_run"))).fetchall()
        end = {r[0]: utc(r[3]) for r in runs}
        first = {}
        for rid, doc, start, _ in runs:
            ev.append((utc(start), ORDER["run_start"], "run_start", s, "document_run", rid, None))
            if end[rid]:
                ev.append((end[rid], ORDER["run_end"], "run_end", s, "document_run", rid, None))
            first[doc] = min(first.get(doc, utc(start)), utc(start))
        for did, created, latest in archive.execute(sql.SQL(
                "SELECT id, created_at, latest_successful_run_id FROM {}").format(sql.Identifier(s, "document"))):
            t0 = first.get(did, utc(created))
            ev.append((t0, ORDER["doc_first"], "doc_first", s, "document", did, None))
            if latest:
                ev.append((max(end.get(latest) or t0, t0), ORDER["doc_final"], "doc_final", s, "document", did, None))
        o = f"{env}_odoo"
        for table in ODOO_TABLES:
            rows = archive.execute(sql.SQL("SELECT id, create_date, write_date FROM {}").format(
                sql.Identifier(o, table))).fetchall()
            hist = history(archive, o, table) if table in HISTORY else {}
            for rid, created, written in rows:
                versions = hist.get(rid, [])
                for ts, idx in versions:
                    ev.append((ts, ORDER["version"], "version", o, table, rid, idx))
                if versions:   # the current row last, never before its last version
                    ev.append((max(utc(written) or versions[-1][0], versions[-1][0]), ORDER["row"], "row", o,
                               table, rid, None))
                else:          # one known state: written once, at its creation (spec, replay table)
                    ev.append((utc(created), ORDER["row"], "row", o, table, rid, None))
    return ev


class Writer:
    def __init__(self, archive, live):
        self.archive, self.live = archive, live
        self.t = {(s, t): Table(archive, s, t) for s, t in tables()}
        self.rows = 0
        self.prepare_versions()

    def prepare_versions(self):
        """Every history version's payload, once, into a temporary table of this archive session: reading one
        version from a history value of up to 72 MB took 0.7 s; a temporary table needs no write access to archive
        and writes no WAL."""
        a = self.archive
        a.execute("CREATE TEMP TABLE IF NOT EXISTS replay_versions (sch text, tbl text, id int, idx int, "
                  "payload text, PRIMARY KEY (sch, tbl, id, idx))")
        for env in ENVS:
            for table, (hcol, _) in HISTORY.items():
                a.execute(sql.SQL("INSERT INTO replay_versions SELECT %s, %s, t.id, h.o - 1, (h.e -> 'payload')::text "
                                  "FROM {} t, jsonb_array_elements(CASE WHEN jsonb_typeof(t.{c}) = 'array' THEN t.{c} "
                                  "ELSE '[]' END) WITH ORDINALITY h(e, o) ON CONFLICT DO NOTHING").format(
                    sql.Identifier(f"{env}_odoo", table), c=sql.Identifier(hcol)), (f"{env}_odoo", table))
        a.commit()

    def run_started(self, row):
        if row["completed_at"] is None:          # a run that never ended: its only known state
            return row
        return {**row, **{c: None for c in RUN_COMPLETION}, **RUN_STARTED}

    def version(self, schema, table, rid, idx, ts):
        hcol, col = HISTORY[table]
        row = self.t[schema, table].by_ids(self.archive, [rid])[0]
        payload = self.archive.execute("SELECT payload FROM replay_versions WHERE sch = %s AND tbl = %s AND id = %s "
                                       "AND idx = %s", (schema, table, rid, idx)).fetchone()[0]
        row = {**row, col: payload, "write_date": ts.replace(tzinfo=None)}
        if "published_at" in row and (row["published_at"] is None or ts < utc(row["published_at"])):
            row.update({c: None for c in PUBLISHED})
        return row

    def children(self, schema, rid):
        n = 0
        for child in CHILDREN:
            c = self.t[schema, child]
            n += c.write(self.live, c.by_run(self.archive, rid))
        return n

    def apply(self, group):
        """One event time: every write in one transaction."""
        once = defaultdict(list)
        for ts, _, kind, schema, table, rid, idx in sorted(group, key=lambda e: e[1]):
            t = self.t[schema, table]
            if kind == "doc_first":
                row = t.by_ids(self.archive, [rid])[0]
                self.rows += t.write(self.live, [{**row, "latest_successful_run_id": None,
                                                  "updated_at": row["created_at"]}])
            elif kind == "run_start":
                row = t.by_ids(self.archive, [rid])[0]
                self.rows += t.write(self.live, [self.run_started(row)])
                if row["completed_at"] is None:     # a run that never ended: its children now, its only event
                    self.rows += self.children(schema, rid)
            elif kind == "run_end":
                self.rows += t.write(self.live, t.by_ids(self.archive, [rid]))
                self.rows += self.children(schema, rid)
            elif kind == "version":
                self.rows += t.write(self.live, [self.version(schema, table, rid, idx, ts)])
            else:                                   # doc_final, row: the archive's row as it is
                once[schema, table].append(rid)
        for (schema, table), ids in once.items():
            t = self.t[schema, table]
            self.rows += t.write(self.live, t.by_ids(self.archive, ids))
        self.live.commit()


def baseline(ev, t0):
    """Before the first run: per row, only its last write before t0 (spec: written once, unpaced)."""
    last = {}
    for e in sorted(e for e in ev if e[0] < t0):
        last[(e[3], e[4], e[5])] = e
    return list(last.values())


def fill(archive, live, speedup, target_minutes):
    if live_rows(live):
        sys.exit("live is not empty; a fill starts from an empty live (the full new fill)")
    ev = events(archive)
    runs = [e[0] for e in ev if e[2] == "run_start"]
    t0, t_end = min(runs), max(e[0] for e in ev)
    base = baseline(ev, t0)
    paced = sorted(e for e in ev if e[0] >= t0)
    span = (t_end - t0).total_seconds()
    speedup = speedup or span / (target_minutes * 60)
    log(f"{len(ev)} writes: {len(base)} baseline before {t0:%Y-%m-%d %H:%M:%S}, {len(paced)} paced over "
        f"{span / 86400:.1f} days; speed-up {speedup:,.0f} (about {span / speedup / 60:.1f} min)")
    w = Writer(archive, live)
    w.apply(base)
    log(f"baseline written: {w.rows} rows")
    groups = defaultdict(list)
    for e in paced:
        groups[e[0]].append(e)
    start, last_log, behind = time.monotonic(), 0.0, 0.0
    for i, ts in enumerate(sorted(groups)):
        due = start + (ts - t0).total_seconds() / speedup
        now = time.monotonic()
        if due > now:
            time.sleep(due - now)
        else:
            behind = max(behind, now - due)
        w.apply(groups[ts])
        if time.monotonic() - last_log >= 10:
            last_log = time.monotonic()
            el = last_log - start
            log(f"replayed to {ts:%Y-%m-%d %H:%M}, {i + 1}/{len(groups)} event times, {w.rows} rows, "
                f"{w.rows / max(el, 1):.0f} rows/s, at most {behind:.1f} s behind schedule")
    el = time.monotonic() - start
    log(f"fill done: {w.rows} rows in {el:.0f} s ({w.rows / max(el, 1):.0f} rows/s, speed-up kept "
        f"{span / max(el, 1):,.0f}, at most {behind:.1f} s behind schedule)")


def slice_(archive, live, target, gap):
    env, rid = target.split(":")
    schema, table = f"{env}_odoo", "request_ticket_result"
    rid = int(rid)
    if not live.execute(sql.SQL("SELECT 1 FROM {} WHERE id = %s").format(sql.Identifier(schema, table)),
                        (rid,)).fetchone():
        sys.exit(f"{target}: not in live; slice mode replays into a filled live")
    w = Writer(archive, live)
    versions = history(archive, schema, table).get(rid, [])
    steps = [("version", ts, idx) for ts, idx in versions] + [("row", None, None)]
    for n, (kind, ts, idx) in enumerate(steps, 1):
        t = w.t[schema, table]
        row = w.version(schema, table, rid, idx, ts) if kind == "version" else t.by_ids(archive, [rid])[0]
        t.write(live, [row])
        live.commit()
        log(f"save {n}/{len(steps)} of {target} committed ({kind})")
        if n < len(steps):
            time.sleep(gap)


def verify(archive, live):
    bad = 0
    for schema, table in tables():
        t = Table(archive, schema, table)
        q = sql.SQL("SELECT count(*), md5(coalesce(string_agg(row({})::text, '|' ORDER BY id), '')) FROM {}").format(
            sql.SQL(", ").join(sql.Identifier(n) for n in t.names), sql.Identifier(schema, table))
        a, b = archive.execute(q).fetchone(), live.execute(q).fetchone()
        same = a == b
        bad += not same
        print(f"{schema}.{table}: archive {a[0]}, live {b[0]}, content {'same' if same else 'DIFFERS'}")
    print(f"verify: {len(list(tables())) - bad} of {len(list(tables()))} tables equal")
    return bad == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    sub.add_parser("init")
    f = sub.add_parser("fill")
    f.add_argument("--speedup", type=float, help="replayed seconds per real second (default: from --minutes)")
    f.add_argument("--minutes", type=float, default=10, help="target length of the whole replay")
    s = sub.add_parser("slice")
    s.add_argument("target", help="env:result id, e.g. stg:1")
    s.add_argument("--gap", type=float, default=30, help="seconds between saves")
    sub.add_parser("verify")
    args = ap.parse_args()
    archive, live = connect("archive"), connect("live")
    if args.mode == "init":
        init(archive, live)
    elif args.mode == "fill":
        fill(archive, live, args.speedup, args.minutes)
    elif args.mode == "slice":
        slice_(archive, live, args.target, args.gap)
    else:
        sys.exit(0 if verify(archive, live) else 1)


if __name__ == "__main__":
    main()

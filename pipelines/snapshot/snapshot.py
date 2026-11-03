#!/usr/bin/env python3
"""Copy the client's OCR tables, read only, into one snapshot folder: a CSV per table, schema.sql, manifest.json.

    PGSERVICEFILE=$PWD/.scratch_pg/pg_service.conf PGPASSFILE=$PWD/.scratch_pg/pgpass \\
      python3 -I pipelines/snapshot/snapshot.py                  # copy all four sources into data/snapshots/<id>/
    python3 -I pipelines/snapshot/snapshot.py --verify <dir>     # recheck a copy's files against its manifest

Spec: docs/specs/data-path.md#snapshot
Each source is read through its reader role (psql service) in one REPEATABLE READ READ ONLY transaction. Only the
columns and rows the spec allows are selected, so nothing else leaves the client. No host, role or password is printed
or written.
"""

import argparse
import csv
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
csv.field_size_limit(sys.maxsize)  # a template row is several MB
OUT = ROOT / "data" / "snapshots"

# Schema in the lab -> psql service of its reader role (.scratch_pg/pg_service.conf).
SOURCES = {
    "dev_svc": "ocr-service-reader",
    "stg_svc": "stg-ocr-service-reader",
    "dev_odoo": "odoo-reader",
    "stg_odoo": "stg-odoo-reader",
}

SVC_TABLES = ["document", "document_run", "document_page", "document_unit", "match_candidate",
              "element_record", "run_element", "run_stage"]
ODOO_TABLES = ["ocr_element", "ocr_document_template", "ocr_element_prompt",
               "product_document", "ir_attachment", "request_ticket_result"]

# Never selected, besides every column with a foreign key to res_users or res_partner.
EXCLUDE = {
    "document": {"owner_user"},                      # an Odoo user id, no foreign key
    "document_run": {"triggered_by"},                # an Odoo user id, no foreign key
    "ocr_document_template": {"name"},         # some titles name a person
    # product_document: the product link, and Odoo fields the OCR question does not need (some exist in dev only)
    "product_document": {"product_tmpl_id", "client_field_1", "client_field_2",
                         "client_field_3"},
    "ir_attachment": {"db_datas", "index_content", "access_token"},
}
PERSON_TABLES = {"res_users", "res_partner"}

OCR_REQUESTED = "ocr_request_ticket_id IS NOT NULL"
WHERE = {
    "product_document": OCR_REQUESTED,
    "ir_attachment": ("name LIKE 'ocr-page-%' OR id IN (SELECT ir_attachment_id FROM product_document WHERE "
                      f"{OCR_REQUESTED} UNION SELECT origin_attachment_id FROM product_document WHERE {OCR_REQUESTED})"),
}


def strip_history(col, payload_path=None):
    """A history array with each entry's author removed (and one path inside its payload, if given)."""
    entry = "e - 'create_uid' - 'create_user_name'"
    if payload_path:
        entry = (f"CASE WHEN e ? 'payload' THEN jsonb_set({entry}, '{{payload}}', (e->'payload') #- '{payload_path}') "
                 f"ELSE {entry} END")
    return (f"CASE WHEN jsonb_typeof({col}) = 'array' THEN coalesce((SELECT jsonb_agg({entry} ORDER BY o) "
            f"FROM jsonb_array_elements({col}) WITH ORDINALITY AS h(e, o)), '[]'::jsonb) ELSE {col} END")


# Column -> the expression selected in its place (same name and type).
REWRITE = {
    "request_ticket_result": {
        "result": "result #- '{header,createdBy}'",
        "result_history": strip_history("result_history", "{header,createdBy}"),
    },
    "ocr_document_template": {"settings_history": strip_history("settings_history")},
}

# History columns: copied, but never written to `live` (spec row 24), so left out of the largest event.
HISTORY = {"request_ticket_result": "result_history", "ocr_document_template": "settings_history"}

# Columns added by the copy: (name, type, expression).
EXTRA = {
    "request_ticket_result": [(
        "saved_by_domain", "text NOT NULL",
        "coalesce((SELECT CASE lower(split_part(coalesce(nullif(p.email, ''), u.login), '@', 2)) "
        "WHEN 'team.example' THEN 'team' WHEN 'client.example' THEN 'client' ELSE 'other' END "
        "FROM res_users u LEFT JOIN res_partner p ON p.id = u.partner_id WHERE u.id = t.write_uid), 'other')",
    )],
}

CATALOG_SQL = """
SELECT c.relname, a.attnum, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
       EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conrelid = c.oid AND k.contype = 'p' AND a.attnum = ANY (k.conkey)),
       coalesce((SELECT string_agg(ft.relname, ',') FROM pg_constraint f JOIN pg_class ft ON ft.oid = f.confrelid
                 WHERE f.conrelid = c.oid AND f.contype = 'f' AND a.attnum = ANY (f.conkey)), '')
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_attribute a ON a.attrelid = c.oid
WHERE n.nspname = 'public' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
  AND c.relname IN ({tables})
ORDER BY 1, 2
"""

# A user's name, as it would appear as a whole JSON string (the people check).
NAMES_CTE = ("WITH names AS (SELECT DISTINCT to_json(p.name)::text AS q FROM res_users u "
             "JOIN res_partner p ON p.id = u.partner_id WHERE length(p.name) >= 4)")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def psql(service, args, stdin=None):
    """Run psql on one service; stop with psql's own error message (it holds no password)."""
    cmd = ["psql", f"service={service}", "-X", "-q", "-v", "ON_ERROR_STOP=1", *args]
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, env={**os.environ, "PGCLIENTENCODING": "UTF8"})
    if r.returncode != 0:
        sys.exit(f"psql failed on {service}: {r.stderr.strip()}")
    return r.stdout


def catalog(service, tables):
    """{table: [column dicts]} for the tables, from the source's catalog."""
    sql = CATALOG_SQL.format(tables=", ".join(f"'{t}'" for t in tables))
    out = psql(service, ["-A", "-t", "-F", "\t", "-c", sql])
    cols = {t: [] for t in tables}
    for line in out.splitlines():
        table, _, name, typ, notnull, pk, fks = line.split("\t")
        cols[table].append({"name": name, "type": typ, "notnull": notnull == "t", "pk": pk == "t",
                            "fks": set(filter(None, fks.split(",")))})
    missing = [t for t, c in cols.items() if not c]
    if missing:
        sys.exit(f"{service}: tables not found: {', '.join(missing)}")
    return cols


def plan_table(table, columns):
    """The SELECT for one table and the DDL of what it returns."""
    keep = [c for c in columns if c["name"] not in EXCLUDE.get(table, set()) and not c["fks"] & PERSON_TABLES]
    rewrite = REWRITE.get(table, {})
    exprs = [f'{rewrite[c["name"]]} AS "{c["name"]}"' if c["name"] in rewrite else f't."{c["name"]}"' for c in keep]
    ddl = [f'"{c["name"]}" {c["type"]}{" NOT NULL" if c["notnull"] else ""}' for c in keep]
    for name, typ, expr in EXTRA.get(table, []):
        exprs.append(f'{expr} AS "{name}"')
        ddl.append(f'"{name}" {typ}')
    pk = [f'"{c["name"]}"' for c in columns if c["pk"]]
    where = f" WHERE {WHERE[table]}" if table in WHERE else ""
    select = f'SELECT {", ".join(exprs)} FROM public."{table}" t{where} ORDER BY {", ".join("t." + p for p in pk)}'
    return select, ddl, pk, [c["name"] for c in columns if c not in keep]


def copy_source(schema, service, tables, work):
    """One transaction on one source: every table to CSV, then its row stats. Returns the per-table plans."""
    cols = catalog(service, tables)
    is_odoo = schema.endswith("_odoo")
    (work / schema).mkdir()
    plans, script = {}, ["BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;", "SET LOCAL statement_timeout = '15min';"]
    for table in tables:
        select, ddl, pk, dropped = plan_table(table, cols[table])
        csv_path = work / schema / f"{table}.csv"
        stats_path = work / f".stats-{schema}-{table}.csv"
        people = (f"(SELECT count(*) FROM x WHERE EXISTS (SELECT 1 FROM names WHERE strpos(x.j, names.q) > 0))"
                  if is_odoo else "NULL")
        stats = (f"{NAMES_CTE if is_odoo else 'WITH'}{',' if is_odoo else ''} "
                 f"x AS (SELECT row_to_json(s)::text AS j FROM ({select}) s) "
                 f"SELECT count(*), coalesce(max(octet_length(j)), 0), {people} FROM x")
        script.append(f"\\copy ({select}) TO '{csv_path}' WITH (FORMAT csv, HEADER)")
        script.append(f"\\copy ({stats}) TO '{stats_path}' WITH (FORMAT csv)")
        plans[table] = {"select": select, "ddl": ddl, "pk": pk, "dropped": dropped, "csv": csv_path,
                        "stats": stats_path}
    script.append("COMMIT;")
    psql(service, ["-f", "-"], stdin="\n".join(script) + "\n")
    return plans


def count_rows(path, history=None):
    """(rows, largest event): an event is the row as `live` holds it, JSON-encoded as Debezium sends it."""
    rows = largest = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows += 1
            row.pop(history, None)
            largest = max(largest, len(json.dumps(row, ensure_ascii=False).encode()))
    return rows, largest


def schema_sql(all_plans):
    lines = ["-- The copied tables, generated from each source's catalog for the copied columns only."]
    for schema, plans in all_plans.items():
        lines.append(f"\nCREATE SCHEMA {schema};")
        for table, p in plans.items():
            body = ",\n  ".join(p["ddl"] + [f'PRIMARY KEY ({", ".join(p["pk"])})'])
            lines.append(f'CREATE TABLE {schema}."{table}" (\n  {body}\n);')
    return "\n".join(lines) + "\n"


def snapshot():
    if not os.environ.get("PGSERVICEFILE"):
        sys.exit("Set PGSERVICEFILE and PGPASSFILE to the files in .scratch_pg/ (see the runbook).")
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".tmp-", dir=OUT))
    started = datetime.datetime.now(datetime.timezone.utc)
    all_plans, files = {}, []
    try:
        for schema, service in SOURCES.items():
            tables = ODOO_TABLES if schema.endswith("_odoo") else SVC_TABLES
            t0 = datetime.datetime.now(datetime.timezone.utc)
            all_plans[schema] = copy_source(schema, service, tables, work)
            for table, p in all_plans[schema].items():
                with open(p["stats"], newline="") as f:
                    sql_rows, largest, people = next(csv.reader(f))
                p["stats"].unlink()
                rows, largest_event = count_rows(p["csv"], HISTORY.get(table))
                if rows != int(sql_rows):
                    sys.exit(f"{schema}.{table}: {rows} CSV rows, {sql_rows} in the source")
                if people not in ("", "0"):
                    sys.exit(f"{schema}.{table}: {people} rows hold a user's name; nothing kept")
                files.append({
                    "file": f"{schema}/{table}.csv", "source": schema, "table": table, "rows": rows,
                    "bytes": p["csv"].stat().st_size, "largest_row_bytes": int(largest),
                    "largest_event_bytes": largest_event,
                    "people": None if people == "" else int(people), "sha256": sha256(p["csv"]),
                    "select_sha256": hashlib.sha256(p["select"].encode()).hexdigest(),
                    "columns_left_out": p["dropped"],
                })
                print(f"{schema}.{table}: {rows} rows, {files[-1]['bytes']:,} bytes")
            print(f"{schema}: done in {(datetime.datetime.now(datetime.timezone.utc) - t0).seconds} s")
        (work / "schema.sql").write_text(schema_sql(all_plans))
        manifest = {
            "spec": "docs/specs/data-path.md#snapshot",
            "started": started.isoformat(timespec="seconds"),
            "finished": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "schema_sha256": sha256(work / "schema.sql"),
            "files": files,
        }
        text = json.dumps(manifest, indent=2) + "\n"
        (work / "manifest.json").write_text(text)
        copy_id = f"{started:%Y-%m-%d}-{hashlib.sha256(text.encode()).hexdigest()[:12]}"
        final = OUT / copy_id
        work.rename(final)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    print(f"copy {copy_id}: {len(files)} files, {sum(f['rows'] for f in files):,} rows, "
          f"{sum(f['bytes'] for f in files):,} bytes -> {final.relative_to(ROOT)}")
    verify(final)


def check(folder):
    """(manifest, problems): every file the manifest names exists with its sha256 and row count, nothing else is
    in the folder, and the copy id matches the manifest."""
    folder = Path(folder)
    text = (folder / "manifest.json").read_text()
    manifest = json.loads(text)
    problems = []
    if not folder.name.endswith(hashlib.sha256(text.encode()).hexdigest()[:12]):
        problems.append("folder name does not match the manifest's sha256")
    if sha256(folder / "schema.sql") != manifest["schema_sha256"]:
        problems.append("schema.sql: sha256 differs")
    for f in manifest["files"]:
        path = folder / f["file"]
        if not path.exists():
            problems.append(f"{f['file']}: missing")
        elif sha256(path) != f["sha256"]:
            problems.append(f"{f['file']}: sha256 differs")
        elif count_rows(path)[0] != f["rows"]:
            problems.append(f"{f['file']}: row count differs")
        if f["people"] not in (None, 0):
            problems.append(f"{f['file']}: people count {f['people']}")
    listed = {f["file"] for f in manifest["files"]} | {"manifest.json", "schema.sql"}
    extra = sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file()
                   and str(p.relative_to(folder)) not in listed)
    problems += [f"{e}: not in the manifest" for e in extra]
    return manifest, problems


def verify(folder):
    folder = Path(folder)
    manifest, problems = check(folder)
    for p in problems:
        print(f"FAIL {p}")
    print(f"verify {folder.name}: {len(manifest['files'])} files, {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verify", metavar="DIR", help="recheck an existing copy instead of making one")
    args = ap.parse_args()
    verify(args.verify) if args.verify else snapshot()


if __name__ == "__main__":
    main()

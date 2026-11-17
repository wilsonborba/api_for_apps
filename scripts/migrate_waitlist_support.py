#!/usr/bin/env python3
"""Explicit central waitlist schema and support-ticket constraints.

No seed rows, no legacy data copy and no deletion. The dry run only reads. The
apply refuses, without changing rows, when existing tickets would violate a new
constraint.
"""
import argparse
from pathlib import Path
from migrate_app_catalog import ROOT, connection_environment, psql
from migrate_plans import migrate_plans

WAITLIST = ROOT / "migrations/005_central_waitlist.sql"
SUPPORT = ROOT / "migrations/006_support_ticket_constraints.sql"
STATUSES = ("open", "pending", "resolved", "closed")
STATUS_LIST = ",".join(f"'{status}'" for status in STATUSES)


def present(environment, table):
    return psql(environment, ["-c", f"SELECT to_regclass('public.{table}') IS NOT NULL"]) == "t"


def counted(output):
    """Parse `value|count` rows from psql unaligned output."""
    rows = []
    for line in output.splitlines():
        value, _, count = line.rpartition("|")
        rows.append((value, int(count)))
    return rows


def unique_user_key(environment):
    return psql(environment, ["-c", (
        "SELECT EXISTS (SELECT 1 FROM pg_index i JOIN pg_attribute a "
        "ON a.attrelid=i.indrelid AND a.attnum=i.indkey[0] "
        "WHERE i.indrelid='public.defaultdb_user'::regclass AND i.indisunique "
        "AND i.indnkeyatts=1 AND i.indpred IS NULL AND a.attname='uuid_id')"
    )]) == "t"


def ticket_violations(environment):
    """Read-only report of existing tickets that the new constraints would reject."""
    statuses = counted(psql(environment, ["-c", (
        "SELECT status, count(*) FROM public.defaultdb_support_ticket "
        f"WHERE status NOT IN ({STATUS_LIST}) GROUP BY status ORDER BY status"
    )]))
    registered = (
        " AND NOT EXISTS (SELECT 1 FROM public.defaultdb_app a WHERE a.id=t.source_app)"
        if present(environment, "defaultdb_app") else ""
    )
    apps = counted(psql(environment, ["-c", (
        "SELECT t.source_app, count(*) FROM public.defaultdb_support_ticket t "
        f"WHERE t.source_app IS NOT NULL{registered} "
        "GROUP BY t.source_app ORDER BY t.source_app"
    )]))
    return statuses, apps


def migrate_waitlist_support(environment, apply=False):
    print("Waitlist schema: app_waitlist_entries. No seed rows and no legacy data copy.")
    for table in ("defaultdb_user", "defaultdb_support_ticket"):
        if not present(environment, table):
            raise RuntimeError(f"Required table {table} is missing; nothing changed.")
    problems = []
    if not unique_user_key(environment):
        problems.append("defaultdb_user.uuid_id has no single-column unique index")
    statuses, apps = ticket_violations(environment)
    for status, count in statuses:
        problems.append(f"{count} support ticket(s) with status {status!r} outside {STATUSES}")
    for app, count in apps:
        problems.append(f"{count} support ticket(s) with unregistered source_app {app!r}")
    print("Existing rows that would violate the new constraints:", len(problems) and "yes" or "none")
    for problem in problems:
        print(" -", problem)
    if not apply:
        migrate_plans(environment, False)
        print("Dry run: no schema or data changes.")
        return problems
    if problems:
        raise RuntimeError(
            "Refusing to apply: resolve the reported rows explicitly first. Nothing was changed."
        )
    migrate_plans(environment, True)
    psql(environment, ["--single-transaction", "-f", str(WAITLIST)])
    psql(environment, ["--single-transaction", "-f", str(SUPPORT)])
    print("Waitlist schema and support-ticket constraints ready. No rows were added, changed or deleted.")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    try:
        migrate_waitlist_support(connection_environment(args.env_file), args.yes)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()

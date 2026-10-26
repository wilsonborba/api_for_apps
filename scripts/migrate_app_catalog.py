#!/usr/bin/env python3
"""Explicit schema-only foundation for issue #57. No waitlist or ticket changes."""
import argparse
import os
import subprocess
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "migrations" / "001_app_catalog.sql"


def connection_environment(path):
    values = dotenv_values(path)
    required = ("DEFAULT_DB_HOST", "DEFAULT_DB_USER", "DEFAULT_DB_PASSWORD")
    if any(not values.get(key) for key in required):
        raise ValueError("The canonical environment must provide database credentials.")
    if values.get("DEFAULT_DB_NAME") != "appdb":
        raise ValueError("Refusing migration: the explicit target must be appdb.")
    return dict(
        os.environ,
        PGHOST=values["DEFAULT_DB_HOST"],
        PGPORT=values.get("DEFAULT_DB_PORT") or "5432",
        PGUSER=values["DEFAULT_DB_USER"],
        PGPASSWORD=values["DEFAULT_DB_PASSWORD"],
        PGDATABASE="appdb",
        PGSSLMODE=values.get("DEFAULT_DB_SSLMODE") or "require",
        PGCONNECT_TIMEOUT="10",
    )


def psql(environment, arguments):
    result = subprocess.run(
        ["psql", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", *arguments],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Database operation failed. Credentials were not logged.")
    return result.stdout.strip()


def migrate(environment, apply=False):
    present = psql(
        environment,
        ["-c", "SELECT to_regclass('public.defaultdb_app') IS NOT NULL"],
    ) == "t"
    print("Target: appdb.public.defaultdb_app")
    print("Existing table:", "yes" if present else "no")
    if not apply:
        print("Dry run: schema inspection only; no changes.")
        return
    if not present:
        psql(environment, ["--single-transaction", "-f", str(SCHEMA)])
    columns = psql(
        environment,
        ["-c", "SELECT column_name FROM information_schema.columns "
         "WHERE table_schema='public' AND table_name='defaultdb_app' "
         "ORDER BY ordinal_position"],
    ).splitlines()
    if columns != ["id", "name", "is_active"]:
        raise RuntimeError("Existing app catalog differs from the approved schema; not altered.")
    print("App catalog schema ready. No application data, waitlists or tickets changed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--yes", action="store_true")
    arguments = parser.parse_args()
    try:
        migrate(connection_environment(arguments.env_file), arguments.yes)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()

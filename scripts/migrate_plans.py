#!/usr/bin/env python3
"""Explicit schema-only central plan migration. No startup writes or seed rows."""
import argparse
from pathlib import Path
from migrate_app_catalog import ROOT, connection_environment, migrate, psql

SCHEMA = ROOT / "migrations/004_app_plans.sql"


def migrate_plans(environment, apply=False):
    migrate(environment, apply)
    print("Plan schema: app_plans, app_features and plan_features. No seed rows.")
    if apply:
        psql(environment, ["--single-transaction", "-f", str(SCHEMA)])
    else:
        print("Dry run: no plan schema or data changes.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    try:
        migrate_plans(connection_environment(args.env_file), args.yes)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()

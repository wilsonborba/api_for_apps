#!/usr/bin/env python3
"""Explicit schema-only log migration. No startup migrations or data population."""
import argparse
from pathlib import Path
from migrate_app_catalog import ROOT, connection_environment, migrate, psql


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--yes', action='store_true')
    args = parser.parse_args()
    try:
        environment = connection_environment(args.env_file)
        migrate(environment, args.yes)
        schema = ROOT / 'migrations/002_app_logs.sql'
        print('Log schema: defaultdb_app_log; no application data changes.')
        if args.yes:
            psql(environment, ['--single-transaction', '-f', str(schema)])
        else:
            print('Dry run: no log schema changes.')
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()

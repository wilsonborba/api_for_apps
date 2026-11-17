"""Isolated waitlist/support migration checks. No environment file or external database is read."""
import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("waitlist_migration", ROOT / "scripts/migrate_waitlist_support.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
PLAN = "11111111-1111-4111-8111-111111111111"


def fake_psql(statuses="", apps="", unique="t", tables=True, orphans="", user_type="character varying(64)"):
    calls = []

    def run(environment, arguments):
        calls.append(arguments)
        sql = arguments[-1]
        if arguments[0] == "--single-transaction":
            return ""
        if "to_regclass" in sql:
            return "t" if tables else "f"
        if "pg_index" in sql:
            return unique
        if "format_type" in sql:
            return user_type if "defaultdb_support_ticket" in sql else "character varying(64)"
        if "NOT EXISTS (SELECT 1 FROM public.defaultdb_user" in sql:
            return orphans
        if "GROUP BY status" in sql:
            return statuses
        if "GROUP BY t.source_app" in sql:
            return apps
        raise AssertionError(sql)

    return run, calls


class WaitlistSupportMigrationTests(unittest.TestCase):
    def test_waitlist_schema_is_empty_idempotent_typed_and_app_scoped(self):
        with sqlite3.connect(":memory:") as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("CREATE TABLE defaultdb_user(uuid_id TEXT UNIQUE)")
            for path in ("001_app_catalog.sql", "004_app_plans.sql"):
                db.executescript((ROOT / "migrations" / path).read_text().replace("public.", ""))
            schema = migration.WAITLIST.read_text().replace("public.", "")
            db.executescript(schema)
            db.executescript(schema)
            self.assertEqual(db.execute("SELECT count(*) FROM app_waitlist_entries").fetchone()[0], 0)
            for column in db.execute("PRAGMA table_info(app_waitlist_entries)"):
                self.assertNotIn(column[2].upper(), ("JSON", "JSONB", "ARRAY"))
            db.execute("INSERT INTO defaultdb_app(id,name) VALUES('one','One'),('two','Two')")
            db.execute(f"INSERT INTO app_plans(id,app_id,code,name) VALUES('{PLAN}','one','free','Free')")
            db.execute("INSERT INTO defaultdb_user VALUES('u')")
            insert = "INSERT INTO app_waitlist_entries(id,app_id,target_type,plan_id,interest,email,user_id) VALUES"
            db.execute(f"{insert}('a','one','plan','{PLAN}',NULL,'a@example.test','u')")
            db.execute(f"{insert}('b','one','interest',NULL,'news','a@example.test',NULL)")
            for values in [
                f"('c','two','plan','{PLAN}',NULL,'a@example.test',NULL)",
                f"('d','one','plan','{PLAN}',NULL,'a@example.test',NULL)",
                "('e','one','interest',NULL,'news','a@example.test',NULL)",
                "('f','one','plan',NULL,'news','b@example.test',NULL)",
                "('g','one','interest',NULL,'news','B@example.test',NULL)",
                "('h','one','interest',NULL,'news','b@example.test','missing')",
            ]:
                with self.assertRaises(sqlite3.IntegrityError, msg=values):
                    db.execute(insert + values)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE app_waitlist_entries SET status='open'")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(f"DELETE FROM app_plans WHERE id='{PLAN}'")
            self.assertEqual(db.execute("SELECT count(*) FROM app_waitlist_entries").fetchone()[0], 2)

    def test_dry_run_reports_violations_and_never_executes_schema(self):
        run, calls = fake_psql(statuses="archived|2", apps="legacy-app|3", unique="f", orphans="t-1\nt-2", user_type="uuid")
        with patch.object(migration, "psql", run), patch.object(migration, "migrate_plans") as plans:
            problems = migration.migrate_waitlist_support({}, False)
        plans.assert_called_once_with({}, False)
        self.assertEqual(len(problems), 5)
        self.assertTrue(any(problem.startswith("2 support ticket(s) whose user_id") and problem.endswith("t-1, t-2") for problem in problems))
        self.assertTrue(any("'uuid'" in problem for problem in problems))
        self.assertTrue(any("legacy-app" in problem and "3" in problem for problem in problems))
        self.assertTrue(any("archived" in problem and "2" in problem for problem in problems))
        self.assertFalse(any(call[0] == "--single-transaction" for call in calls))
        self.assertFalse(any(word in " ".join(map(str, call)).upper() for call in calls for word in ("DELETE", "UPDATE", "INSERT", "ALTER")))

    def test_apply_refuses_before_any_change_when_rows_would_violate(self):
        run, calls = fake_psql(apps="legacy-app|1")
        with patch.object(migration, "psql", run), patch.object(migration, "migrate_plans") as plans:
            with self.assertRaises(RuntimeError):
                migration.migrate_waitlist_support({}, True)
        plans.assert_not_called()
        self.assertFalse(any(call[0] == "--single-transaction" for call in calls))

    def test_apply_runs_explicit_transactions_without_seed_or_data_rewrites(self):
        run, calls = fake_psql()
        with patch.object(migration, "psql", run), patch.object(migration, "migrate_plans") as plans:
            self.assertEqual(migration.migrate_waitlist_support({}, True), [])
        plans.assert_called_once_with({}, True)
        applied = [call for call in calls if call[0] == "--single-transaction"]
        self.assertEqual(applied, [
            ["--single-transaction", "-f", str(migration.WAITLIST)],
            ["--single-transaction", "-f", str(migration.SUPPORT)],
        ])
        for path in (migration.WAITLIST, migration.SUPPORT):
            text = path.read_text().upper()
            for word in ("INSERT INTO", "DELETE FROM", "UPDATE PUBLIC", "TRUNCATE", "DROP ", "JSON"):
                self.assertNotIn(word, text, path)

    def test_apply_refuses_while_tickets_reference_missing_users(self):
        run, calls = fake_psql(orphans="t-9")
        with patch.object(migration, "psql", run), patch.object(migration, "migrate_plans") as plans:
            with self.assertRaises(RuntimeError):
                migration.migrate_waitlist_support({}, True)
        plans.assert_not_called()
        self.assertFalse(any(call[0] == "--single-transaction" for call in calls))
        self.assertFalse(any("body" in str(call) or "subject" in str(call) for call in calls))

    def test_missing_legacy_tables_stop_without_changes(self):
        run, calls = fake_psql(tables=False)
        with patch.object(migration, "psql", run), patch.object(migration, "migrate_plans"):
            with self.assertRaises(RuntimeError):
                migration.migrate_waitlist_support({}, True)
        self.assertFalse(any(call[0] == "--single-transaction" for call in calls))


if __name__ == "__main__":
    unittest.main()

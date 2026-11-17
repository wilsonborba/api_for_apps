"""Isolated schema/runner checks. No environment file or external database is read."""
import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("plans_migration", ROOT / "scripts/migrate_plans.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class PlansMigrationTests(unittest.TestCase):
    def test_normalized_schema_is_empty_idempotent_and_app_scoped(self):
        with sqlite3.connect(":memory:") as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript((ROOT / "migrations/001_app_catalog.sql").read_text().replace("public.", ""))
            schema = migration.SCHEMA.read_text().replace("public.", "")
            db.executescript(schema)
            db.executescript(schema)
            for table in ("defaultdb_app", "app_plans", "app_features", "plan_features"):
                self.assertEqual(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)
                for column in db.execute(f"PRAGMA table_info({table})"):
                    self.assertNotIn(column[2].upper(), ("JSON", "JSONB", "ARRAY"))
            db.execute("INSERT INTO defaultdb_app(id,name) VALUES('one','One'),('two','Two')")
            db.execute("INSERT INTO app_plans(id,app_id,code,name,is_active) VALUES('p','one','free','Display name',TRUE)")
            db.execute("INSERT INTO app_features(id,app_id,code,name) VALUES('f','one','search','Search'),('other','two','search','Search')")
            db.execute("INSERT INTO plan_features VALUES('one','p','f')")
            for statement in [
                "INSERT INTO app_plans(id,app_id,code,name,is_active) VALUES('paid','one','paid','Paid',TRUE)",
                "INSERT INTO app_plans(id,app_id,code,name) VALUES('duplicate','one','free','Free')",
                "INSERT INTO app_plans(id,app_id,code,name) VALUES('orphan','unknown','free','Free')",
                "INSERT INTO app_plans(id,app_id,code,name) VALUES(NULL,'two','free','Free')",
                "INSERT INTO plan_features VALUES('one','p','other')",
                "INSERT INTO plan_features VALUES('two','p','other')",
                "INSERT INTO plan_features VALUES('one','p','f')",
            ]:
                with self.assertRaises(sqlite3.IntegrityError, msg=statement):
                    db.execute(statement)
            db.execute("DELETE FROM app_features WHERE id='f'")
            self.assertEqual(db.execute("SELECT count(*) FROM plan_features").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM app_plans").fetchone()[0], 1)

    def test_dry_run_never_executes_plan_schema(self):
        with patch.object(migration, "migrate") as catalog, patch.object(migration, "psql") as psql:
            migration.migrate_plans({}, False)
        catalog.assert_called_once_with({}, False)
        psql.assert_not_called()

    def test_apply_is_explicit_transaction_without_seed_commands(self):
        with patch.object(migration, "migrate") as catalog, patch.object(migration, "psql") as psql:
            migration.migrate_plans({}, True)
        catalog.assert_called_once_with({}, True)
        psql.assert_called_once_with({}, ["--single-transaction", "-f", str(migration.SCHEMA)])
        self.assertNotIn("INSERT", migration.SCHEMA.read_text().upper())


if __name__ == "__main__":
    unittest.main()

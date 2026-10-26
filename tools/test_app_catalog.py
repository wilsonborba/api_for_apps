"""The schema fixture is isolated SQLite. It never uses a production connection."""
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "app_catalog_migration", ROOT / "scripts" / "migrate_app_catalog.py"
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class AppCatalogTests(unittest.TestCase):
    def test_catalog_is_idempotent_and_is_a_foreign_key_target(self):
        # SQLite's main schema corresponds to PostgreSQL public for this fixture.
        schema = migration.SCHEMA.read_text().replace("public.defaultdb_app", "defaultdb_app")
        with sqlite3.connect(":memory:") as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(schema)
            connection.executescript(schema)
            self.assertEqual(connection.execute("SELECT count(*) FROM defaultdb_app").fetchone()[0], 0)
            connection.execute("INSERT INTO defaultdb_app(id,name) VALUES('fixture','Fixture')")
            self.assertEqual(connection.execute("SELECT is_active FROM defaultdb_app").fetchone()[0], 1)
            connection.execute("CREATE TABLE fixture_log(app_id TEXT REFERENCES defaultdb_app(id))")
            connection.execute("INSERT INTO fixture_log VALUES('fixture')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO fixture_log VALUES('unknown')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO defaultdb_app(id,name) VALUES('fixture','Duplicate')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO defaultdb_app(id,name) VALUES(NULL,'Invalid')")

    def test_dry_run_does_not_execute_schema(self):
        with patch.object(migration, "psql", return_value="f") as psql:
            migration.migrate({}, apply=False)
        self.assertEqual(psql.call_count, 1)
        self.assertNotIn("-f", psql.call_args.args[1])

    def test_wrong_database_is_rejected_and_dotenv_parses_quoted_password(self):
        with tempfile.TemporaryDirectory(prefix="app-catalog-test-") as directory:
            path = Path(directory) / ".env"
            path.write_text("DEFAULT_DB_HOST=localhost\nDEFAULT_DB_USER=fixture\n"
                            "DEFAULT_DB_PASSWORD='fixture # password'\nDEFAULT_DB_NAME=appdb\n")
            environment = migration.connection_environment(path)
            self.assertEqual(environment["PGPASSWORD"], "fixture # password")
            path.write_text(path.read_text().replace("DEFAULT_DB_NAME=appdb", "DEFAULT_DB_NAME=other"))
            with self.assertRaises(ValueError):
                migration.connection_environment(path)


if __name__ == "__main__":
    unittest.main()

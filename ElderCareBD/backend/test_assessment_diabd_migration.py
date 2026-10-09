import hashlib
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from assessment_diabd_migration import (
    DIABD_ASSESSMENT_COLUMNS,
    MIGRATION_VERSION,
    migrate_assessment_diabd,
)
from assessment_ml_migration import (
    ASSESSMENT_ML_COLUMNS,
    MIGRATION_TABLE,
    MIGRATION_TABLE_SQL,
    MIGRATION_VERSION as FOUNDATION_MIGRATION_VERSION,
)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class AssessmentDiaBDMigrationTest(unittest.TestCase):
    def _fixture(self, root):
        database = Path(root) / "eldercare_bd.db"
        backup = Path(root) / "pre_diabd_v3.db"
        secondary = Path(root) / "eldercare_bd_2.db"
        connection = sqlite3.connect(database)
        connection.execute(
            "CREATE TABLE assessments ("
            "id INTEGER PRIMARY KEY NOT NULL, "
            "patient_id INTEGER NOT NULL, age INTEGER NOT NULL, "
            "systolic_bp INTEGER NOT NULL, diastolic_bp INTEGER NOT NULL, "
            "bmi FLOAT NOT NULL)"
        )
        for name, column_type in ASSESSMENT_ML_COLUMNS.items():
            connection.execute(
                f'ALTER TABLE assessments ADD COLUMN "{name}" {column_type}'
            )
        connection.execute(MIGRATION_TABLE_SQL)
        connection.execute(
            f"INSERT INTO {MIGRATION_TABLE} "
            "(version, applied_at, source_backup_sha256) VALUES (?, ?, ?)",
            (FOUNDATION_MIGRATION_VERSION, "2026-08-26T00:00:00+00:00", "a" * 64),
        )
        connection.execute(
            "INSERT INTO assessments "
            "(id, patient_id, age, systolic_bp, diastolic_bp, bmi) "
            "VALUES (1, 10, 55, 130, 80, 25.0)"
        )
        connection.commit()
        connection.close()
        shutil.copyfile(database, backup)
        shutil.copyfile(database, secondary)
        return database, backup, secondary

    def test_additive_migration_preserves_rows_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            database, backup, secondary = self._fixture(temporary)
            backup_hash = _sha256(backup)
            secondary_hash = _sha256(secondary)

            result = migrate_assessment_diabd(database, backup)
            self.assertTrue(result["applied"])
            self.assertEqual(
                result["added_assessment_columns"],
                list(DIABD_ASSESSMENT_COLUMNS),
            )
            self.assertEqual(_sha256(backup), backup_hash)
            self.assertEqual(_sha256(secondary), secondary_hash)

            connection = sqlite3.connect(database)
            columns = {
                row[1]: row for row in connection.execute(
                    "PRAGMA table_info(assessments)"
                )
            }
            for name, column_type in DIABD_ASSESSMENT_COLUMNS.items():
                self.assertEqual(columns[name][2], column_type)
                self.assertEqual(columns[name][3], 0)
            self.assertEqual(
                connection.execute(
                    "SELECT diabetes_gender, diabetes_random_glucose_mmol_l "
                    "FROM assessments WHERE id = 1"
                ).fetchone(),
                (None, None),
            )
            self.assertEqual(
                connection.execute(
                    f"SELECT COUNT(*) FROM {MIGRATION_TABLE} WHERE version = ?",
                    (MIGRATION_VERSION,),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            connection.close()

            migrated_hash = _sha256(database)
            rerun = migrate_assessment_diabd(database, backup)
            self.assertFalse(rerun["applied"])
            self.assertEqual(_sha256(database), migrated_hash)

    def test_failure_rolls_back_exact_database_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            database, backup, secondary = self._fixture(temporary)
            database_hash = _sha256(database)
            secondary_hash = _sha256(secondary)

            def fail_after_first_column(step):
                if step == "column:assessments.diabetes_gender":
                    raise RuntimeError("synthetic failure")

            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                migrate_assessment_diabd(
                    database,
                    backup,
                    failure_injector=fail_after_first_column,
                )
            self.assertEqual(_sha256(database), database_hash)
            self.assertEqual(_sha256(secondary), secondary_hash)


if __name__ == "__main__":
    unittest.main()

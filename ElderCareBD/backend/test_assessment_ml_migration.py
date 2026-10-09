import hashlib
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import assessment_ml_migration
from assessment_ml_migration import (
    ASSESSMENT_ML_COLUMNS,
    MIGRATION_TABLE_SQL,
    MIGRATION_VERSION,
)
from migrate_assessment_ml import migrate_assessment_ml


BACKEND_DIRECTORY = Path(__file__).resolve().parent
PERSISTENT_DATABASES = (
    BACKEND_DIRECTORY / "eldercare_bd.db",
    BACKEND_DIRECTORY / "eldercare_bd_2.db",
)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _persistent_database_hashes():
    return {
        path.name: _sha256(path)
        for path in PERSISTENT_DATABASES
        if path.is_file()
    }


def _create_pre_task14_database(path):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        f"""
        CREATE TABLE caregivers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            phone_or_email TEXT NOT NULL UNIQUE
        );
        CREATE TABLE caregiver_sessions (
            id INTEGER PRIMARY KEY,
            caregiver_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            FOREIGN KEY(caregiver_id) REFERENCES caregivers(id)
                ON UPDATE CASCADE ON DELETE CASCADE
        );
        CREATE TABLE patients (
            id INTEGER PRIMARY KEY,
            caregiver_id INTEGER,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            FOREIGN KEY(caregiver_id) REFERENCES caregivers(id)
                ON UPDATE CASCADE ON DELETE SET NULL
        );
        CREATE TABLE assessments (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            age INTEGER NOT NULL,
            glucose INTEGER NOT NULL,
            systolic_bp INTEGER NOT NULL,
            diastolic_bp INTEGER NOT NULL,
            bmi FLOAT NOT NULL,
            chest_pain BOOLEAN,
            dizziness BOOLEAN,
            shortness_of_breath BOOLEAN,
            excessive_thirst BOOLEAN,
            fatigue BOOLEAN,
            blurred_vision BOOLEAN,
            diabetes_risk VARCHAR NOT NULL,
            heart_risk VARCHAR NOT NULL,
            overall_risk VARCHAR NOT NULL,
            recommendation TEXT NOT NULL,
            created_at DATETIME,
            height_cm FLOAT,
            weight_kg FLOAT,
            note TEXT,
            FOREIGN KEY(patient_id) REFERENCES patients(id)
                ON UPDATE CASCADE ON DELETE CASCADE
        );
        CREATE TABLE prescriptions (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            doctor_name TEXT,
            FOREIGN KEY(patient_id) REFERENCES patients(id)
                ON UPDATE CASCADE ON DELETE CASCADE
        );
        CREATE TABLE medicines (
            id INTEGER PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            prescription_id INTEGER,
            name TEXT NOT NULL,
            FOREIGN KEY(patient_id) REFERENCES patients(id)
                ON UPDATE CASCADE ON DELETE CASCADE,
            FOREIGN KEY(prescription_id) REFERENCES prescriptions(id)
                ON UPDATE CASCADE ON DELETE SET NULL
        );
        CREATE TABLE typed_audit_values (
            id INTEGER PRIMARY KEY,
            integer_value INTEGER,
            float_value REAL,
            text_value TEXT,
            blob_value BLOB,
            null_value TEXT
        );
        CREATE INDEX idx_assessments_patient_id ON assessments(patient_id);
        CREATE VIEW assessment_identity_view AS
            SELECT id, patient_id FROM assessments;
        CREATE TRIGGER assessment_age_guard
        BEFORE INSERT ON assessments
        WHEN NEW.age < 0
        BEGIN
            SELECT RAISE(ABORT, 'invalid assessment age');
        END;
        {MIGRATION_TABLE_SQL};
        """
    )

    connection.executemany(
        "INSERT INTO caregivers (id, name, phone_or_email) VALUES (?, ?, ?)",
        [
            (value, f"Caregiver {value}", f"caregiver{value}@example.invalid")
            for value in range(1, 14)
        ],
    )
    connection.executemany(
        """
        INSERT INTO caregiver_sessions (id, caregiver_id, token_hash)
        VALUES (?, ?, ?)
        """,
        [(value, value, f"token-{value}") for value in range(1, 5)],
    )
    connection.executemany(
        "INSERT INTO patients (id, caregiver_id, name, age) VALUES (?, ?, ?, ?)",
        [
            (value, ((value - 1) % 13) + 1, f"Patient {value}", 54 + value)
            for value in range(1, 11)
        ],
    )
    connection.executemany(
        """
        INSERT INTO assessments (
            id, patient_id, age, glucose, systolic_bp, diastolic_bp, bmi,
            chest_pain, dizziness, shortness_of_breath, excessive_thirst,
            fatigue, blurred_vision, diabetes_risk, heart_risk, overall_risk,
            recommendation, created_at, height_cm, weight_kg, note
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [
            (
                value,
                ((value - 1) % 10) + 1,
                49 + value,
                80 + value,
                108 + value,
                68 + (value % 7),
                20.25 + value / 2,
                value % 2,
                (value + 1) % 2,
                value % 3 == 0,
                value % 4 == 0,
                value % 5 == 0,
                value % 6 == 0,
                "Low" if value % 2 else "Medium",
                "Low" if value % 3 else "High",
                "Low" if value % 4 else "High",
                f"Historical recommendation {value}",
                f"2026-07-{value:02d}T10:00:00",
                150.5 + value,
                48.75 + value,
                None if value == 1 else f"Historical note {value}",
            )
            for value in range(1, 17)
        ],
    )
    connection.executemany(
        "INSERT INTO prescriptions (id, patient_id, doctor_name) VALUES (?, ?, ?)",
        [
            (value, ((value - 1) % 10) + 1, f"Doctor {value}")
            for value in range(1, 10)
        ],
    )
    connection.executemany(
        """
        INSERT INTO medicines (id, patient_id, prescription_id, name)
        VALUES (?, ?, ?, ?)
        """,
        [
            (
                value,
                ((value - 1) % 9) + 1,
                ((value - 1) % 9) + 1,
                f"Medicine {value}",
            )
            for value in range(1, 14)
        ],
    )
    connection.execute(
        """
        INSERT INTO typed_audit_values (
            id, integer_value, float_value, text_value, blob_value, null_value
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            -17,
            -0.0,
            "Unicode health note: \u09ac\u09be\u0982\u09b2\u09be",
            sqlite3.Binary(b"\x00\xff\x10"),
            None,
        ),
    )
    connection.execute(
        """
        INSERT INTO eldercare_schema_migrations (
            version, applied_at, source_backup_sha256
        ) VALUES (?, ?, ?)
        """,
        (
            "task12a_secure_prescription_foundation_v2",
            "2026-08-22T19:13:07+00:00",
            "a" * 64,
        ),
    )
    connection.commit()
    connection.close()


class AssessmentMlMigrationTests(unittest.TestCase):
    def setUp(self):
        self.persistent_hashes = _persistent_database_hashes()
        self.temporary_directory = tempfile.TemporaryDirectory()
        temporary_root = Path(self.temporary_directory.name)
        self.database_path = temporary_root / "eldercare_bd.db"
        self.backup_path = temporary_root / "pre_task14_backup.db"
        self.secondary_path = temporary_root / "eldercare_bd_2.db"
        _create_pre_task14_database(self.database_path)
        shutil.copy2(self.database_path, self.backup_path)
        shutil.copy2(self.database_path, self.secondary_path)
        self.original_hash = _sha256(self.database_path)
        self.backup_hash = _sha256(self.backup_path)
        self.secondary_hash = _sha256(self.secondary_path)

    def tearDown(self):
        self.temporary_directory.cleanup()
        self.assertEqual(self.persistent_hashes, _persistent_database_hashes())

    def _restore_database(self):
        shutil.copy2(self.backup_path, self.database_path)

    def test_migration_is_additive_and_completed_rerun_is_byte_noop(self):
        before = sqlite3.connect(self.database_path)
        legacy_columns = tuple(
            row[1] for row in before.execute("PRAGMA table_info('assessments')")
        )
        legacy_rows = before.execute(
            f"SELECT {', '.join(legacy_columns)} FROM assessments ORDER BY id"
        ).fetchall()
        old_schema_objects = before.execute(
            """
            SELECT type, name, tbl_name, sql FROM sqlite_master
            WHERE type IN ('index', 'trigger', 'view') ORDER BY type, name
            """
        ).fetchall()
        before.close()

        first = migrate_assessment_ml(self.database_path, self.backup_path)

        self.assertTrue(first["applied"])
        self.assertEqual(first["migration_version"], MIGRATION_VERSION)
        self.assertEqual(first["historical_assessment_count"], 16)
        self.assertTrue(first["historical_assessment_ml_values_null"])
        self.assertTrue(first["record_ids_and_typed_values_preserved"])
        self.assertEqual(
            set(first["added_assessment_columns"]),
            set(ASSESSMENT_ML_COLUMNS),
        )
        self.assertEqual(
            {
                key: first["record_counts"][key]
                for key in (
                    "caregivers",
                    "caregiver_sessions",
                    "patients",
                    "assessments",
                    "prescriptions",
                    "medicines",
                )
            },
            {
                "caregivers": 13,
                "caregiver_sessions": 4,
                "patients": 10,
                "assessments": 16,
                "prescriptions": 9,
                "medicines": 13,
            },
        )

        verification = sqlite3.connect(self.database_path)
        assessment_info = {
            row[1]: {
                "type": row[2],
                "notnull": row[3],
                "default": row[4],
            }
            for row in verification.execute("PRAGMA table_info('assessments')")
        }
        self.assertEqual(
            {
                name: assessment_info[name]["type"]
                for name in ASSESSMENT_ML_COLUMNS
            },
            ASSESSMENT_ML_COLUMNS,
        )
        self.assertTrue(
            all(
                assessment_info[name]["notnull"] == 0
                and assessment_info[name]["default"] is None
                for name in ASSESSMENT_ML_COLUMNS
            )
        )
        self.assertEqual(
            verification.execute(
                f"SELECT {', '.join(legacy_columns)} FROM assessments ORDER BY id"
            ).fetchall(),
            legacy_rows,
        )
        ml_rows = verification.execute(
            f"SELECT {', '.join(ASSESSMENT_ML_COLUMNS)} "
            "FROM assessments ORDER BY id"
        ).fetchall()
        self.assertEqual(len(ml_rows), 16)
        self.assertTrue(all(all(value is None for value in row) for row in ml_rows))
        self.assertEqual(
            verification.execute(
                """
                SELECT version, source_backup_sha256
                FROM eldercare_schema_migrations WHERE version = ?
                """,
                (MIGRATION_VERSION,),
            ).fetchall(),
            [(MIGRATION_VERSION, self.backup_hash)],
        )
        self.assertEqual(
            verification.execute(
                """
                SELECT type, name, tbl_name, sql FROM sqlite_master
                WHERE type IN ('index', 'trigger', 'view') ORDER BY type, name
                """
            ).fetchall(),
            old_schema_objects,
        )
        self.assertEqual(
            verification.execute("PRAGMA integrity_check").fetchone()[0],
            "ok",
        )
        self.assertEqual(
            verification.execute("PRAGMA foreign_key_check").fetchall(),
            [],
        )
        verification.close()
        self.assertEqual(_sha256(self.backup_path), self.backup_hash)
        self.assertEqual(_sha256(self.secondary_path), self.secondary_hash)

        migrated_hash = _sha256(self.database_path)
        second = migrate_assessment_ml(self.database_path, self.backup_path)
        self.assertFalse(second["applied"])
        self.assertEqual(second["added_assessment_columns"], [])
        self.assertEqual(_sha256(self.database_path), migrated_hash)
        self.assertEqual(_sha256(self.backup_path), self.backup_hash)
        self.assertEqual(_sha256(self.secondary_path), self.secondary_hash)

    def test_every_schema_step_rolls_back_to_exact_original_bytes(self):
        steps = [
            *(f"column:assessments.{name}" for name in ASSESSMENT_ML_COLUMNS),
            "marker:table",
            "marker:row",
        ]

        for step in steps:
            with self.subTest(step=step):
                self._restore_database()

                def fail_at_step(current_step, target=step):
                    if current_step == target:
                        raise RuntimeError(f"injected failure at {target}")

                with self.assertRaisesRegex(RuntimeError, "injected failure"):
                    migrate_assessment_ml(
                        self.database_path,
                        self.backup_path,
                        failure_injector=fail_at_step,
                    )
                self.assertEqual(_sha256(self.database_path), self.original_hash)
                self.assertEqual(_sha256(self.backup_path), self.backup_hash)
                self.assertEqual(_sha256(self.secondary_path), self.secondary_hash)

    def test_marker_table_creation_failure_rolls_back_exactly(self):
        connection = sqlite3.connect(self.database_path)
        connection.execute("DROP TABLE eldercare_schema_migrations")
        connection.commit()
        connection.close()
        shutil.copy2(self.database_path, self.backup_path)
        original_without_marker = _sha256(self.database_path)

        def fail_after_marker_table(step):
            if step == "marker:table":
                raise RuntimeError("injected marker table failure")

        with self.assertRaisesRegex(RuntimeError, "marker table failure"):
            migrate_assessment_ml(
                self.database_path,
                self.backup_path,
                failure_injector=fail_after_marker_table,
            )
        self.assertEqual(_sha256(self.database_path), original_without_marker)

    def test_partial_column_or_marker_state_is_refused_without_repair(self):
        scenarios = ("one_column", "marker_only", "all_columns_without_marker")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                self._restore_database()
                connection = sqlite3.connect(self.database_path)
                if scenario == "one_column":
                    name, column_type = next(iter(ASSESSMENT_ML_COLUMNS.items()))
                    connection.execute(
                        f'ALTER TABLE assessments ADD COLUMN "{name}" {column_type}'
                    )
                elif scenario == "marker_only":
                    connection.execute(
                        """
                        INSERT INTO eldercare_schema_migrations (
                            version, applied_at, source_backup_sha256
                        ) VALUES (?, ?, ?)
                        """,
                        (
                            MIGRATION_VERSION,
                            "2026-08-24T00:00:00+00:00",
                            self.backup_hash,
                        ),
                    )
                else:
                    for name, column_type in ASSESSMENT_ML_COLUMNS.items():
                        connection.execute(
                            f'ALTER TABLE assessments ADD COLUMN "{name}" {column_type}'
                        )
                connection.commit()
                connection.close()
                partial_hash = _sha256(self.database_path)

                with self.assertRaisesRegex(RuntimeError, "Partial"):
                    migrate_assessment_ml(self.database_path, self.backup_path)
                self.assertEqual(_sha256(self.database_path), partial_hash)

    def test_completed_marker_backup_mismatch_is_refused_without_changes(self):
        migrate_assessment_ml(self.database_path, self.backup_path)
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            """
            UPDATE eldercare_schema_migrations SET source_backup_sha256 = ?
            WHERE version = ?
            """,
            ("f" * 64, MIGRATION_VERSION),
        )
        connection.commit()
        connection.close()
        tampered_hash = _sha256(self.database_path)

        with self.assertRaisesRegex(RuntimeError, "does not match"):
            migrate_assessment_ml(self.database_path, self.backup_path)
        self.assertEqual(_sha256(self.database_path), tampered_hash)

    def test_backup_must_be_byte_identical_to_locked_unmigrated_database(self):
        backup = sqlite3.connect(self.backup_path)
        backup.execute("UPDATE assessments SET note = 'changed backup' WHERE id = 1")
        backup.commit()
        backup.close()
        before = _sha256(self.database_path)

        with self.assertRaisesRegex(RuntimeError, "byte-identical"):
            migrate_assessment_ml(self.database_path, self.backup_path)
        self.assertEqual(_sha256(self.database_path), before)

    def test_begin_immediate_precedes_migration_state_snapshot(self):
        original_migration_state = assessment_ml_migration._migration_state
        lock_observed = []

        def inspect_lock(connection):
            if not lock_observed:
                contender = sqlite3.connect(self.database_path, timeout=0)
                try:
                    contender.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as exc:
                    lock_observed.append("locked" in str(exc).lower())
                else:
                    contender.rollback()
                    lock_observed.append(False)
                finally:
                    contender.close()
            return original_migration_state(connection)

        with patch(
            "assessment_ml_migration._migration_state",
            side_effect=inspect_lock,
        ):
            migrate_assessment_ml(self.database_path, self.backup_path)

        self.assertEqual(lock_observed, [True])

    def test_integrity_sidecars_and_secondary_names_are_refused(self):
        with self.assertRaisesRegex(RuntimeError, "eldercare_bd_2"):
            migrate_assessment_ml(self.secondary_path, self.backup_path)
        with self.assertRaisesRegex(RuntimeError, "migration backup"):
            migrate_assessment_ml(self.database_path, self.secondary_path)

        journal_path = Path(f"{self.database_path}-journal")
        journal_path.write_bytes(b"unresolved journal")
        try:
            with self.assertRaisesRegex(RuntimeError, "sidecars"):
                migrate_assessment_ml(self.database_path, self.backup_path)
        finally:
            journal_path.unlink()

        broken = sqlite3.connect(self.database_path)
        broken.execute("PRAGMA foreign_keys = OFF")
        broken.execute("UPDATE assessments SET patient_id = 9999 WHERE id = 1")
        broken.commit()
        broken.close()
        broken_hash = _sha256(self.database_path)
        with self.assertRaisesRegex(RuntimeError, "foreign_key_check"):
            migrate_assessment_ml(self.database_path, self.backup_path)
        self.assertEqual(_sha256(self.database_path), broken_hash)

    def test_live_and_backup_wal_modes_are_refused(self):
        live = sqlite3.connect(self.database_path)
        self.assertEqual(live.execute("PRAGMA journal_mode = WAL").fetchone()[0], "wal")
        live.close()
        for sidecar in assessment_ml_migration._sidecar_paths(self.database_path):
            if sidecar.exists():
                sidecar.unlink()
        with self.assertRaisesRegex(RuntimeError, "WAL mode"):
            migrate_assessment_ml(self.database_path, self.backup_path)

        self._restore_database()
        backup = sqlite3.connect(self.backup_path)
        self.assertEqual(
            backup.execute("PRAGMA journal_mode = WAL").fetchone()[0],
            "wal",
        )
        backup.close()
        for sidecar in assessment_ml_migration._sidecar_paths(self.backup_path):
            if sidecar.exists():
                sidecar.unlink()
        with self.assertRaisesRegex(RuntimeError, "Backup WAL mode"):
            migrate_assessment_ml(self.database_path, self.backup_path)

    def test_hardlinked_backup_and_secondary_alias_are_refused(self):
        self.backup_path.unlink()
        try:
            os.link(self.database_path, self.backup_path)
        except OSError as exc:
            self.skipTest(f"Hard links are unavailable: {exc}")
        with self.assertRaisesRegex(RuntimeError, "Backup must be a separate"):
            migrate_assessment_ml(self.database_path, self.backup_path)
        self.assertEqual(_sha256(self.database_path), self.original_hash)

        self.backup_path.unlink()
        shutil.copy2(self.database_path, self.backup_path)
        self.secondary_path.unlink()
        os.link(self.database_path, self.secondary_path)
        with self.assertRaisesRegex(RuntimeError, "Secondary database"):
            migrate_assessment_ml(self.database_path, self.backup_path)
        self.assertEqual(_sha256(self.database_path), self.original_hash)


if __name__ == "__main__":
    unittest.main()

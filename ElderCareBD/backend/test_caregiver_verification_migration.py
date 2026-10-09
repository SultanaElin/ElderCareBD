import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from assessment_ml_migration import MIGRATION_TABLE_SQL
from caregiver_verification_migration import (
    ACTIVE_CHALLENGE_INDEX,
    ACTIVE_LOOKUP_INDEX,
    CAREGIVER_IDENTITY_INDEX,
    EXPIRY_INDEX,
    MIGRATION_VERSION,
    VERIFICATION_TABLE,
    migrate_caregiver_verification,
)


PRIOR_MIGRATION = "fixture_pre_task15_v1"


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _create_fixture(root, *, identities=None):
    root = Path(root)
    database = root / "eldercare_bd.db"
    backup = root / "eldercare_bd.pre_task15.db"
    secondary = root / "eldercare_bd_2.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE caregivers (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR NOT NULL,
            phone_or_email VARCHAR NOT NULL,
            password VARCHAR NOT NULL,
            created_at DATETIME
        );
        CREATE UNIQUE INDEX ix_caregivers_phone_or_email
            ON caregivers (phone_or_email);

        CREATE TABLE caregiver_sessions (
            id INTEGER NOT NULL PRIMARY KEY,
            caregiver_id INTEGER NOT NULL,
            token_hash VARCHAR(64) NOT NULL,
            created_at DATETIME NOT NULL,
            expires_at DATETIME NOT NULL,
            FOREIGN KEY(caregiver_id) REFERENCES caregivers(id)
        );

        CREATE TABLE patients (
            id INTEGER NOT NULL PRIMARY KEY,
            caregiver_id INTEGER,
            name VARCHAR NOT NULL,
            FOREIGN KEY(caregiver_id) REFERENCES caregivers(id)
        );

        CREATE TABLE assessments (
            id INTEGER NOT NULL PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            note TEXT,
            FOREIGN KEY(patient_id) REFERENCES patients(id)
        );

        CREATE TABLE prescriptions (
            id INTEGER NOT NULL PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            note TEXT,
            FOREIGN KEY(patient_id) REFERENCES patients(id)
        );

        CREATE TABLE medicines (
            id INTEGER NOT NULL PRIMARY KEY,
            patient_id INTEGER NOT NULL,
            prescription_id INTEGER,
            name VARCHAR NOT NULL,
            FOREIGN KEY(patient_id) REFERENCES patients(id),
            FOREIGN KEY(prescription_id) REFERENCES prescriptions(id)
        );
        """
    )
    connection.execute(MIGRATION_TABLE_SQL)
    connection.execute(
        "INSERT INTO eldercare_schema_migrations "
        "(version, applied_at, source_backup_sha256) VALUES (?, ?, ?)",
        (PRIOR_MIGRATION, "2026-01-01T00:00:00+00:00", "a" * 64),
    )
    fixture_identities = identities or (
        (1, "Email Caregiver", "  Alice@Example.Invalid  ", "2025-01-02 03:04:05"),
        (2, "SMS Caregiver", "+8801712345678", "2025-02-03 04:05:06"),
        (3, "Legacy Local", "01712345678", "2025-03-04 05:06:07"),
        (4, "Legacy Other", "not an identity", None),
    )
    connection.executemany(
        "INSERT INTO caregivers "
        "(id, name, phone_or_email, password, created_at) VALUES (?, ?, ?, ?, ?)",
        [
            (caregiver_id, name, identity, f"hashed-{caregiver_id}", created_at)
            for caregiver_id, name, identity, created_at in fixture_identities
        ],
    )
    connection.execute(
        "INSERT INTO caregiver_sessions VALUES (?, ?, ?, ?, ?)",
        (1, 1, "b" * 64, "2026-01-01", "2027-01-01"),
    )
    connection.execute(
        "INSERT INTO patients VALUES (?, ?, ?)",
        (11, 1, "Preserved patient"),
    )
    connection.execute(
        "INSERT INTO assessments VALUES (?, ?, ?)",
        (21, 11, "Preserved assessment"),
    )
    connection.execute(
        "INSERT INTO prescriptions VALUES (?, ?, ?)",
        (31, 11, "Preserved prescription"),
    )
    connection.execute(
        "INSERT INTO medicines VALUES (?, ?, ?, ?)",
        (41, 11, 31, "Preserved medicine"),
    )
    connection.commit()
    connection.close()
    shutil.copy2(database, backup)
    secondary.write_bytes(b"secondary-database-sentinel")
    return database, backup, secondary


def _old_rows(database):
    connection = sqlite3.connect(database)
    try:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for table in (
                "caregiver_sessions",
                "patients",
                "assessments",
                "prescriptions",
                "medicines",
            )
        }
    finally:
        connection.close()


def _run_backend_import(database):
    environment = os.environ.copy()
    environment.update(
        {
            "ELDERCARE_DATABASE_URL": f"sqlite:///{Path(database).as_posix()}",
            "ELDERCARE_ENVIRONMENT": "test",
            "ELDERCARE_OTP_DELIVERY_MODE": "capture",
            "ELDERCARE_OTP_HMAC_SECRET": (
                "task15-startup-test-secret-with-at-least-32-characters"
            ),
        }
    )
    return subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=Path(__file__).resolve().parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


class CaregiverVerificationMigrationTest(unittest.TestCase):
    def test_startup_creates_fresh_schema_and_refuses_existing_partial_schema(self):
        with tempfile.TemporaryDirectory(prefix="eldercare-task15-startup-") as root:
            fresh_database = Path(root) / "fresh.db"
            created = _run_backend_import(fresh_database)
            self.assertEqual(created.returncode, 0, created.stderr)

            connection = sqlite3.connect(fresh_database)
            try:
                self.assertIsNotNone(
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                        "AND name = 'caregiver_verifications'"
                    ).fetchone()
                )
                caregiver_column = connection.execute(
                    "SELECT type, [notnull], dflt_value FROM pragma_table_info('caregivers') "
                    "WHERE name = 'identity_normalized'"
                ).fetchone()
                self.assertEqual(caregiver_column, ("VARCHAR(320)", 0, None))
                active_index = connection.execute(
                    "SELECT [unique], partial FROM pragma_index_list(" 
                    "'caregiver_verifications') WHERE name = ?",
                    (ACTIVE_CHALLENGE_INDEX,),
                ).fetchone()
                self.assertEqual(active_index, (1, 1))
                connection.execute(f"DROP INDEX {ACTIVE_CHALLENGE_INDEX}")
                connection.commit()
            finally:
                connection.close()

            partial_hash = _sha256(fresh_database)
            refused_partial = _run_backend_import(fresh_database)
            self.assertNotEqual(refused_partial.returncode, 0)
            self.assertIn(
                "caregiver verification index contract is incomplete",
                refused_partial.stderr.lower(),
            )
            self.assertEqual(_sha256(fresh_database), partial_hash)

            old_root = Path(root) / "old"
            old_root.mkdir()
            old_database, _backup, _secondary = _create_fixture(old_root)
            old_hash = _sha256(old_database)
            refused_old = _run_backend_import(old_database)
            self.assertNotEqual(refused_old.returncode, 0)
            self.assertIn(
                "existing database schema is incomplete",
                refused_old.stderr.lower(),
            )
            self.assertEqual(_sha256(old_database), old_hash)

    def test_additive_backfill_schema_and_exact_idempotent_rerun(self):
        with tempfile.TemporaryDirectory(prefix="eldercare-task15-migration-") as root:
            database, backup, secondary = _create_fixture(root)
            backup_hash = _sha256(backup)
            secondary_hash = _sha256(secondary)
            old_rows = _old_rows(database)

            result = migrate_caregiver_verification(database, backup)

            self.assertTrue(result["applied"])
            self.assertEqual(result["migration_version"], MIGRATION_VERSION)
            self.assertEqual(result["backup_sha256"], backup_hash)
            self.assertEqual(result["historical_caregiver_count"], 4)
            self.assertEqual(
                result["historical_identity_counts"],
                {"email": 1, "sms": 1, "legacy_unclassified": 2},
            )
            self.assertEqual(
                result["added_caregiver_columns"],
                [
                    "identity_normalized",
                    "verification_status",
                    "verified_at",
                    "primary_verification_channel",
                ],
            )
            self.assertEqual(result["created_table"], VERIFICATION_TABLE)
            self.assertEqual(_sha256(backup), backup_hash)
            self.assertEqual(_sha256(secondary), secondary_hash)
            self.assertEqual(_old_rows(database), old_rows)

            connection = sqlite3.connect(database)
            try:
                caregiver_columns = {
                    row[1]: row
                    for row in connection.execute(
                        "PRAGMA table_info(caregivers)"
                    ).fetchall()
                }
                self.assertEqual(
                    caregiver_columns["identity_normalized"][2],
                    "VARCHAR(320)",
                )
                self.assertEqual(caregiver_columns["verification_status"][2], "VARCHAR(16)")
                self.assertEqual(caregiver_columns["verification_status"][3], 1)
                self.assertEqual(caregiver_columns["verification_status"][4], "'pending'")
                self.assertEqual(caregiver_columns["verified_at"][2], "DATETIME")
                self.assertEqual(
                    caregiver_columns["primary_verification_channel"][2],
                    "VARCHAR(5)",
                )

                caregivers = connection.execute(
                    "SELECT id, identity_normalized, verification_status, verified_at, "
                    "primary_verification_channel FROM caregivers ORDER BY id"
                ).fetchall()
                self.assertEqual(
                    caregivers[:3],
                    [
                        (
                            1,
                            "alice@example.invalid",
                            "verified",
                            "2025-01-02 03:04:05",
                            "email",
                        ),
                        (
                            2,
                            "+8801712345678",
                            "verified",
                            "2025-02-03 04:05:06",
                            "sms",
                        ),
                        (3, None, "verified", "2025-03-04 05:06:07", None),
                    ],
                )
                self.assertEqual(caregivers[3][1], None)
                self.assertEqual(caregivers[3][2], "verified")
                self.assertIsNotNone(caregivers[3][3])
                self.assertEqual(caregivers[3][4], None)

                verification_columns = {
                    row[1]: row
                    for row in connection.execute(
                        "PRAGMA table_info(caregiver_verifications)"
                    ).fetchall()
                }
                self.assertEqual(len(verification_columns), 16)
                self.assertEqual(verification_columns["channel"][2], "VARCHAR(5)")
                self.assertEqual(
                    verification_columns["destination_normalized"][2],
                    "VARCHAR(320)",
                )
                self.assertEqual(verification_columns["failed_attempts"][4], "0")
                self.assertEqual(verification_columns["max_attempts"][4], "5")
                self.assertEqual(verification_columns["resend_count"][4], "0")
                self.assertEqual(verification_columns["delivery_status"][4], "'sent'")
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM caregiver_verifications"
                    ).fetchone()[0],
                    0,
                )

                index_rows = {
                    row[1]: row
                    for row in connection.execute(
                        "PRAGMA index_list(caregiver_verifications)"
                    ).fetchall()
                }
                self.assertEqual(
                    set(index_rows),
                    {ACTIVE_LOOKUP_INDEX, EXPIRY_INDEX, ACTIVE_CHALLENGE_INDEX},
                )
                self.assertEqual(index_rows[ACTIVE_CHALLENGE_INDEX][2], 1)
                self.assertEqual(index_rows[ACTIVE_CHALLENGE_INDEX][4], 1)
                caregiver_indexes = {
                    row[1]: row
                    for row in connection.execute(
                        "PRAGMA index_list(caregivers)"
                    ).fetchall()
                }
                self.assertEqual(caregiver_indexes[CAREGIVER_IDENTITY_INDEX][2], 1)
                marker = connection.execute(
                    "SELECT source_backup_sha256 FROM eldercare_schema_migrations "
                    "WHERE version = ?",
                    (MIGRATION_VERSION,),
                ).fetchone()
                self.assertEqual(marker, (backup_hash,))
                self.assertEqual(
                    connection.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                connection.close()

            completed_hash = _sha256(database)
            rerun = migrate_caregiver_verification(database, backup)
            self.assertFalse(rerun["applied"])
            self.assertEqual(rerun["added_caregiver_columns"], [])
            self.assertIsNone(rerun["created_table"])
            self.assertEqual(_sha256(database), completed_hash)
            self.assertEqual(rerun["database_sha256_before"], completed_hash)
            self.assertEqual(rerun["database_sha256_after"], completed_hash)

    def test_indexes_enforce_normalized_identity_and_one_active_challenge(self):
        with tempfile.TemporaryDirectory(prefix="eldercare-task15-constraints-") as root:
            database, backup, _secondary = _create_fixture(root)
            migrate_caregiver_verification(database, backup)
            connection = sqlite3.connect(database)
            connection.execute("PRAGMA foreign_keys = ON")
            challenge = (
                1,
                "email",
                "alice@example.invalid",
                "d" * 64,
                "e" * 64,
                "2026-01-01",
                "2026-01-01 00:10:00",
                "2026-01-01 00:01:00",
                "2026-01-01",
            )
            insert_sql = """
                INSERT INTO caregiver_verifications (
                    caregiver_id, channel, destination_normalized,
                    otp_digest, otp_salt, created_at, expires_at,
                    resend_available_at, resend_window_started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            connection.execute(insert_sql, challenge)
            connection.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(insert_sql, challenge)
            connection.rollback()

            connection.execute(
                "UPDATE caregiver_verifications SET invalidated_at = ? WHERE caregiver_id = ?",
                ("2026-01-01 00:02:00", 1),
            )
            connection.execute(insert_sql, challenge)
            connection.commit()
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM caregiver_verifications WHERE caregiver_id = 1"
                ).fetchone()[0],
                2,
            )

            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE caregivers SET identity_normalized = ? WHERE id = ?",
                    ("alice@example.invalid", 2),
                )
            connection.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(insert_sql, (999,) + challenge[1:])
            connection.rollback()

            connection.execute(insert_sql, (4,) + challenge[1:])
            connection.commit()
            connection.execute("DELETE FROM caregivers WHERE id = 4")
            connection.commit()
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM caregiver_verifications WHERE caregiver_id = 4"
                ).fetchone()[0],
                0,
            )
            connection.close()

    def test_injected_failures_restore_exact_database_bytes(self):
        failure_steps = (
            "column:caregivers.identity_normalized",
            "backfill:caregivers",
            f"index:{CAREGIVER_IDENTITY_INDEX}",
            f"table:{VERIFICATION_TABLE}",
            f"index:{ACTIVE_CHALLENGE_INDEX}",
            "marker:row",
        )
        for failure_step in failure_steps:
            with self.subTest(step=failure_step), tempfile.TemporaryDirectory(
                prefix="eldercare-task15-rollback-"
            ) as root:
                database, backup, secondary = _create_fixture(root)
                database_hash = _sha256(database)
                backup_hash = _sha256(backup)
                secondary_hash = _sha256(secondary)

                def inject(step):
                    if step == failure_step:
                        raise RuntimeError(f"injected failure at {step}")

                with self.assertRaisesRegex(RuntimeError, "injected failure"):
                    migrate_caregiver_verification(
                        database,
                        backup,
                        failure_injector=inject,
                    )

                self.assertEqual(_sha256(database), database_hash)
                self.assertEqual(_sha256(backup), backup_hash)
                self.assertEqual(_sha256(secondary), secondary_hash)
                connection = sqlite3.connect(database)
                caregiver_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(caregivers)")
                }
                self.assertNotIn("verification_status", caregiver_columns)
                self.assertIsNone(
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                        (VERIFICATION_TABLE,),
                    ).fetchone()
                )
                self.assertIsNone(
                    connection.execute(
                        "SELECT 1 FROM eldercare_schema_migrations WHERE version = ?",
                        (MIGRATION_VERSION,),
                    ).fetchone()
                )
                connection.close()

    def test_refuses_unsafe_targets_sidecars_partial_state_and_bad_backup(self):
        with tempfile.TemporaryDirectory(prefix="eldercare-task15-refusal-") as root:
            database, backup, secondary = _create_fixture(root)
            wrong_name = Path(root) / "other.db"
            shutil.copy2(database, wrong_name)
            with self.assertRaisesRegex(RuntimeError, "non-authoritative"):
                migrate_caregiver_verification(wrong_name, backup)
            with self.assertRaisesRegex(RuntimeError, "eldercare_bd_2"):
                migrate_caregiver_verification(secondary, backup)
            with self.assertRaisesRegex(RuntimeError, "eldercare_bd_2"):
                migrate_caregiver_verification(database, secondary)

            sidecar = Path(f"{database}-wal")
            sidecar.write_bytes(b"unsafe-sidecar")
            with self.assertRaisesRegex(RuntimeError, "sidecars"):
                migrate_caregiver_verification(database, backup)
            sidecar.unlink()

            mismatched_backup = Path(root) / "different.backup.db"
            shutil.copy2(backup, mismatched_backup)
            with mismatched_backup.open("ab") as output:
                output.write(b"different")
            with self.assertRaisesRegex(RuntimeError, "byte-identical"):
                migrate_caregiver_verification(database, mismatched_backup)

            partial_database = Path(root) / "partial" / "eldercare_bd.db"
            partial_database.parent.mkdir()
            partial_backup = partial_database.with_name("preimage.db")
            shutil.copy2(database, partial_database)
            shutil.copy2(database, partial_backup)
            partial_connection = sqlite3.connect(partial_database)
            partial_connection.execute(
                "ALTER TABLE caregivers ADD COLUMN identity_normalized VARCHAR"
            )
            partial_connection.commit()
            partial_connection.close()
            partial_hash = _sha256(partial_database)
            with self.assertRaisesRegex(RuntimeError, "Partial caregiver OTP"):
                migrate_caregiver_verification(partial_database, partial_backup)
            self.assertEqual(_sha256(partial_database), partial_hash)

    def test_normalization_collision_aborts_without_changes(self):
        identities = (
            (1, "First", "Case@Example.Invalid", "2025-01-01"),
            (2, "Second", " case@example.invalid ", "2025-01-02"),
        )
        with tempfile.TemporaryDirectory(prefix="eldercare-task15-collision-") as root:
            database, backup, secondary = _create_fixture(root, identities=identities)
            before_hash = _sha256(database)
            secondary_hash = _sha256(secondary)
            with self.assertRaisesRegex(RuntimeError, "collide after normalization"):
                migrate_caregiver_verification(database, backup)
            self.assertEqual(_sha256(database), before_hash)
            self.assertEqual(_sha256(secondary), secondary_hash)


if __name__ == "__main__":
    unittest.main()

"""Additive, transactional Task 18A1 daily-observation migration."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


AUTHORITATIVE_DATABASE_NAME = "eldercare_bd.db"
REFUSED_DATABASE_NAME = "eldercare_bd_2.db"
MIGRATION_TABLE = "eldercare_schema_migrations"
MIGRATION_VERSION = "task18a1_patient_daily_observations_v1"
OBSERVATION_TABLE = "patient_daily_observations"

TABLE_SQL = f"""
CREATE TABLE {OBSERVATION_TABLE} (
    id INTEGER NOT NULL PRIMARY KEY,
    patient_id INTEGER NOT NULL,
    observation_date DATE NOT NULL,
    recorded_at DATETIME NOT NULL,
    systolic_bp FLOAT,
    diastolic_bp FLOAT,
    glucose_value FLOAT,
    glucose_unit VARCHAR(16),
    glucose_context VARCHAR(50),
    pulse_bpm FLOAT,
    spo2_percent FLOAT,
    temperature_value FLOAT,
    temperature_unit VARCHAR(1),
    weight_kg FLOAT,
    symptoms TEXT,
    notes TEXT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT ux_patient_daily_observations_patient_date
        UNIQUE (patient_id, observation_date),
    FOREIGN KEY(patient_id) REFERENCES patients (id)
        ON DELETE CASCADE ON UPDATE CASCADE
)
"""

INDEX_SQL = f"""
CREATE INDEX ix_patient_daily_observations_patient_date
ON {OBSERVATION_TABLE} (patient_id, observation_date)
"""


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _require_no_sidecars(path):
    path = Path(path)
    sidecars = [
        Path(f"{path}-wal"),
        Path(f"{path}-shm"),
        Path(f"{path}-journal"),
    ]
    if any(candidate.exists() for candidate in sidecars):
        raise RuntimeError("SQLite sidecar files must be absent before migration.")


def _read_only_connection(path):
    connection = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA query_only = ON")
    return connection


def _validate_integrity(connection):
    integrity = connection.execute("PRAGMA integrity_check").fetchall()
    if integrity != [("ok",)]:
        raise RuntimeError(f"SQLite integrity_check failed: {integrity!r}")
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise RuntimeError(f"SQLite foreign_key_check failed: {foreign_keys!r}")


def _table_exists(connection, table_name):
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def _marker(connection):
    if not _table_exists(connection, MIGRATION_TABLE):
        raise RuntimeError("The existing migration marker table is required.")
    return connection.execute(
        f"SELECT source_backup_sha256 FROM {_quote(MIGRATION_TABLE)} "
        "WHERE version = ?",
        (MIGRATION_VERSION,),
    ).fetchone()


def _migration_state(connection):
    table_present = _table_exists(connection, OBSERVATION_TABLE)
    marker = _marker(connection)
    if table_present and marker is not None:
        return "complete", marker[0]
    if not table_present and marker is None:
        return "unmigrated", None
    return "partial", marker[0] if marker is not None else None


def _existing_data_snapshot(connection):
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "AND name NOT IN (?, ?) ORDER BY name",
            (MIGRATION_TABLE, OBSERVATION_TABLE),
        )
    ]
    return {
        table_name: tuple(
            connection.execute(
                f"SELECT * FROM {_quote(table_name)} ORDER BY rowid"
            ).fetchall()
        )
        for table_name in tables
    }


def _existing_object_snapshot(connection):
    return tuple(
        connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' "
            "AND tbl_name NOT IN (?, ?) "
            "AND name NOT IN (?, ?) ORDER BY type, name",
            (
                MIGRATION_TABLE,
                OBSERVATION_TABLE,
                MIGRATION_TABLE,
                "ix_patient_daily_observations_patient_date",
            ),
        ).fetchall()
    )


def _preexisting_markers(connection):
    return tuple(
        connection.execute(
            f"SELECT version, applied_at, source_backup_sha256 "
            f"FROM {_quote(MIGRATION_TABLE)} WHERE version <> ? ORDER BY version",
            (MIGRATION_VERSION,),
        ).fetchall()
    )


def _verify_schema(connection):
    expected_columns = (
        "id",
        "patient_id",
        "observation_date",
        "recorded_at",
        "systolic_bp",
        "diastolic_bp",
        "glucose_value",
        "glucose_unit",
        "glucose_context",
        "pulse_bpm",
        "spo2_percent",
        "temperature_value",
        "temperature_unit",
        "weight_kg",
        "symptoms",
        "notes",
        "created_at",
        "updated_at",
    )
    columns = tuple(
        row[1]
        for row in connection.execute(
            f"PRAGMA table_info({_quote(OBSERVATION_TABLE)})"
        ).fetchall()
    )
    if columns != expected_columns:
        raise RuntimeError("Daily-observation column contract is invalid.")

    foreign_keys = connection.execute(
        f"PRAGMA foreign_key_list({_quote(OBSERVATION_TABLE)})"
    ).fetchall()
    matching = [
        row
        for row in foreign_keys
        if row[2] == "patients"
        and row[3] == "patient_id"
        and row[4] == "id"
        and row[5].upper() == "CASCADE"
        and row[6].upper() == "CASCADE"
    ]
    if len(matching) != 1:
        raise RuntimeError("Daily-observation patient foreign key is invalid.")

    indexes = {
        row[1]: bool(row[2])
        for row in connection.execute(
            f"PRAGMA index_list({_quote(OBSERVATION_TABLE)})"
        ).fetchall()
    }
    if indexes.get("ix_patient_daily_observations_patient_date") is not False:
        raise RuntimeError("Daily-observation lookup index is invalid.")
    if not any(indexes.values()):
        raise RuntimeError("Daily-observation patient/date uniqueness is missing.")


def _verify_marker(connection, backup_hash):
    rows = connection.execute(
        f"SELECT source_backup_sha256 FROM {_quote(MIGRATION_TABLE)} "
        "WHERE version = ?",
        (MIGRATION_VERSION,),
    ).fetchall()
    if rows != [(backup_hash,)]:
        raise RuntimeError("Daily-observation migration marker is invalid.")


def migrate_daily_observations(database_path, backup_path, *, failure_injector=None):
    database_path = Path(database_path).resolve()
    backup_path = Path(backup_path).resolve()
    if database_path.name != AUTHORITATIVE_DATABASE_NAME:
        raise RuntimeError("Refusing to migrate a non-authoritative database.")
    if backup_path.name == REFUSED_DATABASE_NAME:
        raise RuntimeError("Refusing to use eldercare_bd_2.db as a backup.")
    if not database_path.is_file() or not backup_path.is_file():
        raise RuntimeError("Database and verified backup files are required.")
    if database_path == backup_path or os.path.samefile(database_path, backup_path):
        raise RuntimeError("Backup must be a separate file.")

    secondary_path = database_path.with_name(REFUSED_DATABASE_NAME)
    secondary_hash = (
        _sha256_file(secondary_path) if secondary_path.is_file() else None
    )
    _require_no_sidecars(database_path)
    _require_no_sidecars(backup_path)
    before_hash = _sha256_file(database_path)
    backup_hash = _sha256_file(backup_path)

    backup_connection = _read_only_connection(backup_path)
    try:
        _validate_integrity(backup_connection)
        backup_state, _ = _migration_state(backup_connection)
        if backup_state != "unmigrated":
            raise RuntimeError("Backup must be the unmigrated Task 18A1 preimage.")
    finally:
        backup_connection.close()

    read_only = _read_only_connection(database_path)
    try:
        _validate_integrity(read_only)
        state, marker_hash = _migration_state(read_only)
        if state == "partial":
            raise RuntimeError("Partial Task 18A1 migration detected.")
        if state == "complete":
            if marker_hash != backup_hash:
                raise RuntimeError("Migration marker does not match the backup.")
            _verify_schema(read_only)
            _verify_marker(read_only, backup_hash)
    finally:
        read_only.close()

    if state == "complete":
        after_hash = _sha256_file(database_path)
        if after_hash != before_hash:
            raise RuntimeError("Completed migration rerun was not a byte no-op.")
        return {
            "migration_version": MIGRATION_VERSION,
            "applied": False,
            "database_sha256_before": before_hash,
            "database_sha256_after": after_hash,
            "backup_sha256": backup_hash,
            "integrity_check": "ok",
            "foreign_key_issues": 0,
            "preexisting_data_preserved": True,
            "backup_unchanged": True,
            "secondary_database_unchanged": True,
        }

    if before_hash != backup_hash:
        raise RuntimeError("Backup must be byte-identical before migration.")

    connection = sqlite3.connect(database_path, timeout=10)
    locked = False
    try:
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
            raise RuntimeError("WAL mode must be checkpointed and disabled first.")
        connection.execute("BEGIN IMMEDIATE")
        locked = True
        if _sha256_file(database_path) != before_hash:
            raise RuntimeError("Database changed before the migration lock.")
        if _sha256_file(backup_path) != backup_hash:
            raise RuntimeError("Verified backup changed before migration.")
        _validate_integrity(connection)
        before_data = _existing_data_snapshot(connection)
        before_objects = _existing_object_snapshot(connection)
        before_markers = _preexisting_markers(connection)

        connection.execute(TABLE_SQL)
        if failure_injector is not None:
            failure_injector("table:patient_daily_observations")
        connection.execute(INDEX_SQL)
        if failure_injector is not None:
            failure_injector("index:patient_daily_observations")
        connection.execute(
            f"INSERT INTO {_quote(MIGRATION_TABLE)} "
            "(version, applied_at, source_backup_sha256) VALUES (?, ?, ?)",
            (
                MIGRATION_VERSION,
                datetime.now(timezone.utc).isoformat(),
                backup_hash,
            ),
        )
        if failure_injector is not None:
            failure_injector("marker:row")

        _verify_schema(connection)
        _verify_marker(connection, backup_hash)
        if _existing_data_snapshot(connection) != before_data:
            raise RuntimeError("Pre-existing table data changed during migration.")
        if _existing_object_snapshot(connection) != before_objects:
            raise RuntimeError("Pre-existing schema objects changed during migration.")
        if _preexisting_markers(connection) != before_markers:
            raise RuntimeError("Pre-existing migration markers changed.")
        _validate_integrity(connection)
        connection.commit()
        locked = False
    except Exception as exc:
        if locked:
            connection.rollback()
        connection.close()
        _require_no_sidecars(database_path)
        if _sha256_file(database_path) != before_hash:
            raise RuntimeError(
                "Migration rollback did not restore the database bytes."
            ) from exc
        if _sha256_file(backup_path) != backup_hash:
            raise RuntimeError("Verified backup changed during migration.") from exc
        current_secondary_hash = (
            _sha256_file(secondary_path) if secondary_path.is_file() else None
        )
        if current_secondary_hash != secondary_hash:
            raise RuntimeError("Secondary database changed during migration.") from exc
        raise
    else:
        connection.close()

    reopened = _read_only_connection(database_path)
    try:
        _validate_integrity(reopened)
        _verify_schema(reopened)
        _verify_marker(reopened, backup_hash)
        if _existing_data_snapshot(reopened) != before_data:
            raise RuntimeError("Committed pre-existing data changed.")
        if _existing_object_snapshot(reopened) != before_objects:
            raise RuntimeError("Committed pre-existing schema objects changed.")
        if _preexisting_markers(reopened) != before_markers:
            raise RuntimeError("Committed pre-existing markers changed.")
    finally:
        reopened.close()

    _require_no_sidecars(database_path)
    after_hash = _sha256_file(database_path)
    if _sha256_file(backup_path) != backup_hash:
        raise RuntimeError("Verified backup changed during migration.")
    current_secondary_hash = (
        _sha256_file(secondary_path) if secondary_path.is_file() else None
    )
    if current_secondary_hash != secondary_hash:
        raise RuntimeError("Secondary database changed during migration.")

    return {
        "migration_version": MIGRATION_VERSION,
        "applied": True,
        "database_sha256_before": before_hash,
        "database_sha256_after": after_hash,
        "backup_sha256": backup_hash,
        "integrity_check": "ok",
        "foreign_key_issues": 0,
        "preexisting_data_preserved": True,
        "backup_unchanged": True,
        "secondary_database_unchanged": True,
    }

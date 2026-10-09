"""Additive Task 14 DiaBD-v3 assessment provenance migration."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from assessment_ml_migration import (
    ASSESSMENT_ML_COLUMNS,
    AUTHORITATIVE_DATABASE_NAME,
    MIGRATION_TABLE,
    MIGRATION_VERSION as FOUNDATION_MIGRATION_VERSION,
    REFUSED_DATABASE_NAME,
    _column_snapshot,
    _historical_assessment_ids,
    _quote,
    _read_only_connection,
    _require_no_sidecars,
    _schema_snapshot,
    _sha256_file,
    _snapshot_digest,
    _table_exists,
    _validate_integrity,
    _validate_marker_table,
    _value_digests,
    _value_reference,
)


MIGRATION_VERSION = "task14_diabd_v3_provenance_v2"
DIABD_ASSESSMENT_COLUMNS = {
    "diabetes_gender": "VARCHAR",
    "diabetes_random_glucose_mmol_l": "FLOAT",
}


def _migration_marker(connection, version):
    if not _table_exists(connection, MIGRATION_TABLE):
        return None
    return connection.execute(
        f"SELECT version, source_backup_sha256 FROM {_quote(MIGRATION_TABLE)} "
        "WHERE version = ?",
        (version,),
    ).fetchone()


def _require_foundation(connection):
    if not _table_exists(connection, "assessments"):
        raise RuntimeError("The assessments table is required for this migration.")
    _validate_marker_table(connection)
    foundation_marker = _migration_marker(connection, FOUNDATION_MIGRATION_VERSION)
    assessment_names = {
        column["name"] for column in _column_snapshot(connection, "assessments")
    }
    if foundation_marker is None or not set(ASSESSMENT_ML_COLUMNS).issubset(
        assessment_names
    ):
        raise RuntimeError("The Task 14 v1 provenance migration must be complete first.")


def _migration_state(connection):
    _require_foundation(connection)
    assessment_names = {
        column["name"] for column in _column_snapshot(connection, "assessments")
    }
    present = set(DIABD_ASSESSMENT_COLUMNS).intersection(assessment_names)
    marker = _migration_marker(connection, MIGRATION_VERSION)
    if present == set(DIABD_ASSESSMENT_COLUMNS) and marker is not None:
        return "complete", marker
    if not present and marker is None:
        return "unmigrated", None
    return "partial", marker


def _expected_column(column_name, column_type, cid):
    return {
        "cid": cid,
        "name": column_name,
        "type": column_type,
        "notnull": 0,
        "default": None,
        "pk": 0,
    }


def _verify_additive_schema(before, after):
    if set(before["tables"]) != set(after["tables"]):
        raise RuntimeError("Unexpected table set after DiaBD migration.")

    for table_name, before_details in before["tables"].items():
        after_details = after["tables"][table_name]
        expected_columns = list(before_details["columns"])
        if table_name == "assessments":
            for column_name, column_type in DIABD_ASSESSMENT_COLUMNS.items():
                expected_columns.append(
                    _expected_column(column_name, column_type, len(expected_columns))
                )
        if tuple(expected_columns) != after_details["columns"]:
            raise RuntimeError("DiaBD migration column declarations are unexpected.")
        if before_details["foreign_keys"] != after_details["foreign_keys"]:
            raise RuntimeError("Foreign-key declarations changed during migration.")
        if before_details["indexes"] != after_details["indexes"]:
            raise RuntimeError("Existing indexes changed during migration.")

    for object_type in ("index", "trigger", "view"):
        before_objects = {
            row for row in before["objects"] if row[0] == object_type
        }
        after_objects = {row for row in after["objects"] if row[0] == object_type}
        if before_objects != after_objects:
            raise RuntimeError(
                f"Existing {object_type} definitions changed during migration."
            )

    before_tables = {
        row[1]: row[3] for row in before["objects"] if row[0] == "table"
    }
    after_tables = {
        row[1]: row[3] for row in after["objects"] if row[0] == "table"
    }
    for table_name, declaration in before_tables.items():
        if table_name != "assessments" and after_tables.get(table_name) != declaration:
            raise RuntimeError("A pre-existing table declaration changed.")


def _reference_without_migration_markers(schema):
    reference = _value_reference(schema)
    reference.pop(MIGRATION_TABLE, None)
    return reference


def _marker_rows(connection, *, exclude_current=False):
    where = " WHERE version <> ?" if exclude_current else ""
    parameters = (MIGRATION_VERSION,) if exclude_current else ()
    return tuple(
        connection.execute(
            f"SELECT version, applied_at, source_backup_sha256 "
            f"FROM {_quote(MIGRATION_TABLE)}{where} ORDER BY version",
            parameters,
        ).fetchall()
    )


def _verify_marker(connection, backup_sha256):
    rows = connection.execute(
        f"SELECT version, source_backup_sha256 FROM {_quote(MIGRATION_TABLE)} "
        "WHERE version = ?",
        (MIGRATION_VERSION,),
    ).fetchall()
    if rows != [(MIGRATION_VERSION, backup_sha256)]:
        raise RuntimeError("DiaBD migration marker verification failed.")


def _verify_new_columns_null(connection, historical_ids):
    if not historical_ids:
        return
    placeholders = ", ".join("?" for _ in historical_ids)
    predicates = " OR ".join(
        f"{_quote(column)} IS NOT NULL" for column in DIABD_ASSESSMENT_COLUMNS
    )
    count = connection.execute(
        f"SELECT COUNT(*) FROM assessments WHERE id IN ({placeholders}) "
        f"AND ({predicates})",
        historical_ids,
    ).fetchone()[0]
    if count:
        raise RuntimeError("Historical DiaBD provenance fields must remain NULL.")


def _secondary_hash(database_path):
    secondary = database_path.with_name(REFUSED_DATABASE_NAME)
    return _sha256_file(secondary) if secondary.is_file() else None


def migrate_assessment_diabd(database_path, backup_path, *, failure_injector=None):
    """Apply or verify the nullable, idempotent DiaBD-v3 provenance migration."""

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
    if secondary_path.is_file() and (
        os.path.samefile(database_path, secondary_path)
        or os.path.samefile(backup_path, secondary_path)
    ):
        raise RuntimeError("Refusing to modify or alias eldercare_bd_2.db.")

    _require_no_sidecars(database_path)
    _require_no_sidecars(backup_path)
    before_hash = _sha256_file(database_path)
    backup_hash = _sha256_file(backup_path)
    secondary_hash = _secondary_hash(database_path)

    backup_connection = _read_only_connection(backup_path)
    try:
        _validate_integrity(backup_connection)
        backup_state, _ = _migration_state(backup_connection)
        if backup_state != "unmigrated":
            raise RuntimeError("Backup must be the unmigrated DiaBD-v3 preimage.")
        backup_schema = _schema_snapshot(backup_connection)
        backup_historical_ids = _historical_assessment_ids(backup_connection)
    finally:
        backup_connection.close()

    connection = sqlite3.connect(database_path, timeout=10)
    locked = False
    applied = False
    before_schema = None
    after_schema = None
    historical_ids = ()
    preserved_values = None
    preserved_markers = None
    added_columns = []
    try:
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RuntimeError("Could not enable SQLite foreign-key enforcement.")
        if connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
            raise RuntimeError("WAL mode must be checkpointed and disabled first.")
        connection.execute("BEGIN IMMEDIATE")
        locked = True
        _require_no_sidecars(database_path)
        if _sha256_file(database_path) != before_hash:
            raise RuntimeError("Database changed before the migration lock.")
        if _sha256_file(backup_path) != backup_hash:
            raise RuntimeError("Verified backup changed before migration.")

        _validate_integrity(connection)
        state, marker = _migration_state(connection)
        if state == "partial":
            raise RuntimeError("Partial DiaBD migration detected; refusing repair.")

        before_schema = _schema_snapshot(connection)
        if state == "unmigrated":
            if before_hash != backup_hash or before_schema != backup_schema:
                raise RuntimeError("Backup must be the byte-identical schema preimage.")
        elif marker[1] != backup_hash:
            raise RuntimeError("DiaBD migration marker does not match this backup.")

        reference = _reference_without_migration_markers(before_schema)
        preserved_values = _value_digests(connection, reference)
        preserved_markers = _marker_rows(connection, exclude_current=True)
        historical_ids = backup_historical_ids

        if state == "unmigrated":
            for column_name, column_type in DIABD_ASSESSMENT_COLUMNS.items():
                connection.execute(
                    f"ALTER TABLE assessments ADD COLUMN "
                    f"{_quote(column_name)} {column_type}"
                )
                added_columns.append(column_name)
                if failure_injector is not None:
                    failure_injector(f"column:assessments.{column_name}")
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
            applied = True

        after_schema = _schema_snapshot(connection)
        if state == "unmigrated":
            _verify_additive_schema(before_schema, after_schema)
        else:
            _verify_additive_schema(backup_schema, after_schema)
        _verify_marker(connection, backup_hash)
        if _marker_rows(connection, exclude_current=True) != preserved_markers:
            raise RuntimeError("Pre-existing migration markers changed.")
        if _value_digests(connection, reference) != preserved_values:
            raise RuntimeError("Pre-existing IDs or typed values changed.")
        _verify_new_columns_null(connection, historical_ids)
        _validate_integrity(connection)
        connection.commit()
        locked = False
    except Exception as exc:
        if locked:
            connection.rollback()
        connection.close()
        _require_no_sidecars(database_path)
        if _sha256_file(database_path) != before_hash:
            raise RuntimeError("Migration rollback did not restore database bytes.") from exc
        if _sha256_file(backup_path) != backup_hash:
            raise RuntimeError("Verified backup changed during migration.") from exc
        if _secondary_hash(database_path) != secondary_hash:
            raise RuntimeError("Secondary database changed during migration.") from exc
        raise
    else:
        connection.close()

    reopened = _read_only_connection(database_path)
    try:
        _validate_integrity(reopened)
        if _schema_snapshot(reopened) != after_schema:
            raise RuntimeError("Committed schema differs after reopen.")
        _verify_marker(reopened, backup_hash)
        if _value_digests(reopened, reference) != preserved_values:
            raise RuntimeError("Committed pre-existing values changed.")
        if _marker_rows(reopened, exclude_current=True) != preserved_markers:
            raise RuntimeError("Committed pre-existing markers changed.")
        _verify_new_columns_null(reopened, historical_ids)
    finally:
        reopened.close()

    _require_no_sidecars(database_path)
    after_hash = _sha256_file(database_path)
    if not applied and after_hash != before_hash:
        raise RuntimeError("Completed DiaBD migration rerun was not a byte no-op.")
    if _sha256_file(backup_path) != backup_hash:
        raise RuntimeError("Verified backup changed during migration.")
    if _secondary_hash(database_path) != secondary_hash:
        raise RuntimeError("Secondary database changed during migration.")

    return {
        "migration_version": MIGRATION_VERSION,
        "applied": applied,
        "database": database_path.name,
        "backup_sha256": backup_hash,
        "database_sha256_before": before_hash,
        "database_sha256_after": after_hash,
        "schema_sha256_before": _snapshot_digest(before_schema),
        "schema_sha256_after": _snapshot_digest(after_schema),
        "historical_assessment_count": len(historical_ids),
        "historical_assessment_diabd_values_null": True,
        "record_ids_and_typed_values_preserved": True,
        "foreign_key_issues": 0,
        "added_assessment_columns": added_columns,
        "backup_unchanged": True,
        "secondary_database_unchanged": True,
    }

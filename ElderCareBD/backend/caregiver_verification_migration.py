"""Safe additive Task 15 caregiver OTP schema migration."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from assessment_ml_migration import (
    AUTHORITATIVE_DATABASE_NAME,
    MIGRATION_TABLE,
    MIGRATION_TABLE_SQL,
    REFUSED_DATABASE_NAME,
    _column_snapshot,
    _normalize_sql,
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


MIGRATION_VERSION = "task15_caregiver_otp_v1"
VERIFICATION_TABLE = "caregiver_verifications"

CAREGIVER_COLUMNS = (
    ("identity_normalized", "VARCHAR(320)"),
    ("verification_status", "VARCHAR(16) NOT NULL DEFAULT 'pending'"),
    ("verified_at", "DATETIME"),
    ("primary_verification_channel", "VARCHAR(5)"),
)

CAREGIVER_IDENTITY_INDEX = "ix_caregivers_identity_normalized"
ACTIVE_LOOKUP_INDEX = "ix_caregiver_verifications_active_lookup"
EXPIRY_INDEX = "ix_caregiver_verifications_expires_at"
ACTIVE_CHALLENGE_INDEX = "ux_caregiver_verifications_active_caregiver"

CAREGIVER_IDENTITY_INDEX_SQL = f"""
    CREATE UNIQUE INDEX {CAREGIVER_IDENTITY_INDEX}
    ON caregivers (identity_normalized)
"""

VERIFICATION_TABLE_SQL = f"""
    CREATE TABLE {VERIFICATION_TABLE} (
        id INTEGER NOT NULL PRIMARY KEY,
        caregiver_id INTEGER NOT NULL,
        channel VARCHAR(5) NOT NULL,
        destination_normalized VARCHAR(320) NOT NULL,
        otp_digest VARCHAR(64) NOT NULL,
        otp_salt VARCHAR(64) NOT NULL,
        created_at DATETIME NOT NULL,
        expires_at DATETIME NOT NULL,
        resend_available_at DATETIME NOT NULL,
        resend_window_started_at DATETIME NOT NULL,
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 5,
        resend_count INTEGER NOT NULL DEFAULT 0,
        delivery_status VARCHAR(16) NOT NULL DEFAULT 'sent',
        consumed_at DATETIME,
        invalidated_at DATETIME,
        FOREIGN KEY(caregiver_id) REFERENCES caregivers(id) ON DELETE CASCADE
    )
"""

ACTIVE_LOOKUP_INDEX_SQL = f"""
    CREATE INDEX {ACTIVE_LOOKUP_INDEX}
    ON {VERIFICATION_TABLE} (
        caregiver_id,
        channel,
        consumed_at,
        invalidated_at,
        created_at
    )
"""

EXPIRY_INDEX_SQL = f"""
    CREATE INDEX {EXPIRY_INDEX}
    ON {VERIFICATION_TABLE} (expires_at)
"""

ACTIVE_CHALLENGE_INDEX_SQL = f"""
    CREATE UNIQUE INDEX {ACTIVE_CHALLENGE_INDEX}
    ON {VERIFICATION_TABLE} (caregiver_id)
    WHERE consumed_at IS NULL AND invalidated_at IS NULL
"""

_EMAIL_LOCAL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$")
_EMAIL_DOMAIN_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_E164_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")


def _normalize_historical_identity(raw_value):
    value = (raw_value or "").strip()
    if _E164_PATTERN.fullmatch(value):
        return value, "sms"

    if len(value) > 320 or value.count("@") != 1 or any(
        character.isspace() for character in value
    ):
        return None, None
    local, domain = value.rsplit("@", 1)
    if (
        not local
        or len(local) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or _EMAIL_LOCAL_PATTERN.fullmatch(local) is None
    ):
        return None, None
    if not domain or len(domain) > 255:
        return None, None
    labels = domain.split(".")
    if len(labels) < 2 or any(
        _EMAIL_DOMAIN_LABEL_PATTERN.fullmatch(label) is None for label in labels
    ):
        return None, None
    return value.lower(), "email"


def _migration_marker(connection):
    if not _table_exists(connection, MIGRATION_TABLE):
        return None
    return connection.execute(
        f"SELECT version, applied_at, source_backup_sha256 "
        f"FROM {_quote(MIGRATION_TABLE)} WHERE version = ?",
        (MIGRATION_VERSION,),
    ).fetchone()


def _object_names(connection):
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table', 'index', 'trigger', 'view')"
        ).fetchall()
    }


def _migration_state(connection):
    if not _table_exists(connection, "caregivers"):
        raise RuntimeError("The caregivers table is required for this migration.")
    caregiver_names = {
        column["name"] for column in _column_snapshot(connection, "caregivers")
    }
    object_names = _object_names(connection)
    requested_columns = {name for name, _declaration in CAREGIVER_COLUMNS}
    requested_objects = {
        VERIFICATION_TABLE,
        CAREGIVER_IDENTITY_INDEX,
        ACTIVE_LOOKUP_INDEX,
        EXPIRY_INDEX,
        ACTIVE_CHALLENGE_INDEX,
    }
    present_features = requested_columns.intersection(caregiver_names) | (
        requested_objects.intersection(object_names)
    )

    _validate_marker_table(connection)
    marker = _migration_marker(connection)
    complete = requested_columns.issubset(caregiver_names) and requested_objects.issubset(
        object_names
    )
    if complete and marker is not None:
        return "complete", marker
    if not present_features and marker is None:
        return "unmigrated", None
    return "partial", marker


def _expected_column(name, column_type, cid, *, notnull=0, default=None, pk=0):
    return {
        "cid": cid,
        "name": name,
        "type": column_type,
        "notnull": notnull,
        "default": default,
        "pk": pk,
    }


def _expected_verification_columns():
    specifications = (
        ("id", "INTEGER", 1, None, 1),
        ("caregiver_id", "INTEGER", 1, None, 0),
        ("channel", "VARCHAR(5)", 1, None, 0),
        ("destination_normalized", "VARCHAR(320)", 1, None, 0),
        ("otp_digest", "VARCHAR(64)", 1, None, 0),
        ("otp_salt", "VARCHAR(64)", 1, None, 0),
        ("created_at", "DATETIME", 1, None, 0),
        ("expires_at", "DATETIME", 1, None, 0),
        ("resend_available_at", "DATETIME", 1, None, 0),
        ("resend_window_started_at", "DATETIME", 1, None, 0),
        ("failed_attempts", "INTEGER", 1, "0", 0),
        ("max_attempts", "INTEGER", 1, "5", 0),
        ("resend_count", "INTEGER", 1, "0", 0),
        ("delivery_status", "VARCHAR(16)", 1, "'sent'", 0),
        ("consumed_at", "DATETIME", 0, None, 0),
        ("invalidated_at", "DATETIME", 0, None, 0),
    )
    return tuple(
        _expected_column(
            name,
            column_type,
            cid,
            notnull=notnull,
            default=default,
            pk=pk,
        )
        for cid, (name, column_type, notnull, default, pk) in enumerate(
            specifications
        )
    )


def _index_details(connection, table_name):
    details = {}
    for row in connection.execute(
        f"PRAGMA index_list({_quote(table_name)})"
    ).fetchall():
        name = row[1]
        columns = tuple(
            index_row[2]
            for index_row in connection.execute(
                f"PRAGMA index_info({_quote(name)})"
            ).fetchall()
        )
        sql_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            (name,),
        ).fetchone()
        details[name] = {
            "unique": row[2],
            "origin": row[3],
            "partial": row[4],
            "columns": columns,
            "sql": _normalize_sql(sql_row[0] if sql_row is not None else None),
        }
    return details


def _expected_added_caregiver_columns(start_cid):
    return (
        _expected_column("identity_normalized", "VARCHAR(320)", start_cid),
        _expected_column(
            "verification_status",
            "VARCHAR(16)",
            start_cid + 1,
            notnull=1,
            default="'pending'",
        ),
        _expected_column("verified_at", "DATETIME", start_cid + 2),
        _expected_column(
            "primary_verification_channel",
            "VARCHAR(5)",
            start_cid + 3,
        ),
    )


def _snapshot_index_details(schema, table_name):
    sql_by_name = {
        row[1]: row[3]
        for row in schema["objects"]
        if row[0] == "index" and row[2] == table_name
    }
    details = {}
    for row, column_rows in schema["tables"][table_name]["indexes"]:
        name = row[1]
        details[name] = {
            "unique": row[2],
            "origin": row[3],
            "partial": row[4],
            "columns": tuple(column_row[2] for column_row in column_rows),
            "sql": sql_by_name.get(name),
        }
    return details


def _verify_expected_schema(connection, backup_schema):
    current = _schema_snapshot(connection)
    backup_tables = backup_schema["tables"]
    expected_table_names = set(backup_tables) | {VERIFICATION_TABLE, MIGRATION_TABLE}
    if set(current["tables"]) != expected_table_names:
        raise RuntimeError("Unexpected table set after caregiver OTP migration.")

    for table_name, backup_details in backup_tables.items():
        current_details = current["tables"][table_name]
        expected_columns = backup_details["columns"]
        if table_name == "caregivers":
            expected_columns += _expected_added_caregiver_columns(
                len(backup_details["columns"])
            )
        if current_details["columns"] != expected_columns:
            raise RuntimeError("A table has unexpected column declarations.")
        if current_details["foreign_keys"] != backup_details["foreign_keys"]:
            raise RuntimeError("A pre-existing foreign-key declaration changed.")

        backup_indexes = _snapshot_index_details(backup_schema, table_name)
        current_indexes = _index_details(connection, table_name)
        if table_name == "caregivers":
            identity_index = current_indexes.pop(CAREGIVER_IDENTITY_INDEX, None)
            if identity_index != {
                "unique": 1,
                "origin": "c",
                "partial": 0,
                "columns": ("identity_normalized",),
                "sql": _normalize_sql(CAREGIVER_IDENTITY_INDEX_SQL),
            }:
                raise RuntimeError("The caregiver normalized-identity index is invalid.")
        if set(current_indexes) != set(backup_indexes):
            raise RuntimeError("A pre-existing index set changed.")
        for index_name, expected in backup_indexes.items():
            if current_indexes[index_name] != expected:
                raise RuntimeError("A pre-existing index declaration changed.")

    verification_details = current["tables"][VERIFICATION_TABLE]
    if verification_details["columns"] != _expected_verification_columns():
        raise RuntimeError("The caregiver verification table columns are invalid.")
    if verification_details["foreign_keys"] != (
        (0, 0, "caregivers", "caregiver_id", "id", "NO ACTION", "CASCADE", "NONE"),
    ):
        raise RuntimeError("The caregiver verification foreign key is invalid.")

    expected_verification_indexes = {
        ACTIVE_LOOKUP_INDEX: {
            "unique": 0,
            "origin": "c",
            "partial": 0,
            "columns": (
                "caregiver_id",
                "channel",
                "consumed_at",
                "invalidated_at",
                "created_at",
            ),
            "sql": _normalize_sql(ACTIVE_LOOKUP_INDEX_SQL),
        },
        EXPIRY_INDEX: {
            "unique": 0,
            "origin": "c",
            "partial": 0,
            "columns": ("expires_at",),
            "sql": _normalize_sql(EXPIRY_INDEX_SQL),
        },
        ACTIVE_CHALLENGE_INDEX: {
            "unique": 1,
            "origin": "c",
            "partial": 1,
            "columns": ("caregiver_id",),
            "sql": _normalize_sql(ACTIVE_CHALLENGE_INDEX_SQL),
        },
    }
    if _index_details(connection, VERIFICATION_TABLE) != expected_verification_indexes:
        raise RuntimeError("The caregiver verification indexes are invalid.")

    table_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (VERIFICATION_TABLE,),
    ).fetchone()[0]
    if _normalize_sql(table_sql) != _normalize_sql(VERIFICATION_TABLE_SQL):
        raise RuntimeError("The caregiver verification table declaration is invalid.")

    backup_objects = {
        (row[0], row[1]): (row[2], row[3]) for row in backup_schema["objects"]
    }
    current_objects = {
        (row[0], row[1]): (row[2], row[3]) for row in current["objects"]
    }
    additions = {
        ("table", VERIFICATION_TABLE),
        ("index", CAREGIVER_IDENTITY_INDEX),
        ("index", ACTIVE_LOOKUP_INDEX),
        ("index", EXPIRY_INDEX),
        ("index", ACTIVE_CHALLENGE_INDEX),
    }
    if ("table", MIGRATION_TABLE) not in backup_objects:
        additions.update(
            {
                ("table", MIGRATION_TABLE),
                ("index", f"sqlite_autoindex_{MIGRATION_TABLE}_1"),
            }
        )
    if set(current_objects) != set(backup_objects) | additions:
        raise RuntimeError("Unexpected schema objects exist after migration.")
    for key, expected in backup_objects.items():
        if key == ("table", "caregivers"):
            continue
        if current_objects.get(key) != expected:
            raise RuntimeError("A pre-existing schema object changed.")

    _validate_marker_table(connection)
    return current


def _reference_without_markers(schema):
    reference = _value_reference(schema)
    reference.pop(MIGRATION_TABLE, None)
    return reference


def _marker_rows(connection, *, exclude_current=False):
    if not _table_exists(connection, MIGRATION_TABLE):
        return ()
    where = " WHERE version <> ?" if exclude_current else ""
    parameters = (MIGRATION_VERSION,) if exclude_current else ()
    return tuple(
        connection.execute(
            f"SELECT version, applied_at, source_backup_sha256 "
            f"FROM {_quote(MIGRATION_TABLE)}{where} ORDER BY version",
            parameters,
        ).fetchall()
    )


def _historical_manifest(connection):
    rows = connection.execute(
        "SELECT id, phone_or_email, created_at FROM caregivers ORDER BY id"
    ).fetchall()
    manifest = []
    normalized_owners = {}
    for caregiver_id, identity, created_at in rows:
        normalized, channel = _normalize_historical_identity(identity)
        if normalized is not None:
            existing_id = normalized_owners.get(normalized)
            if existing_id is not None:
                raise RuntimeError(
                    "Historical caregiver identities collide after normalization."
                )
            normalized_owners[normalized] = caregiver_id
        manifest.append((caregiver_id, normalized, channel, created_at))
    return tuple(manifest)


def _verify_historical_backfill(connection, manifest, marker_applied_at):
    rows = {
        row[0]: row[1:]
        for row in connection.execute(
            "SELECT id, identity_normalized, verification_status, verified_at, "
            "primary_verification_channel FROM caregivers ORDER BY id"
        ).fetchall()
    }
    for caregiver_id, normalized, channel, created_at in manifest:
        expected = (
            normalized,
            "verified",
            created_at if created_at is not None else marker_applied_at,
            channel,
        )
        if rows.get(caregiver_id) != expected:
            raise RuntimeError("Historical caregiver verification backfill is invalid.")


def _verify_marker(connection, backup_sha256):
    rows = connection.execute(
        f"SELECT version, source_backup_sha256 FROM {_quote(MIGRATION_TABLE)} "
        "WHERE version = ?",
        (MIGRATION_VERSION,),
    ).fetchall()
    if rows != [(MIGRATION_VERSION, backup_sha256)]:
        raise RuntimeError("Caregiver OTP migration marker verification failed.")


def _inject(failure_injector, step):
    if failure_injector is not None:
        failure_injector(step)


def _apply_migration(connection, manifest, backup_sha256, failure_injector):
    applied_at = datetime.now(timezone.utc).isoformat()
    added_columns = []
    for column_name, declaration in CAREGIVER_COLUMNS:
        connection.execute(
            f"ALTER TABLE caregivers ADD COLUMN {_quote(column_name)} {declaration}"
        )
        added_columns.append(column_name)
        _inject(failure_injector, f"column:caregivers.{column_name}")

    for caregiver_id, normalized, channel, created_at in manifest:
        connection.execute(
            "UPDATE caregivers SET identity_normalized = ?, "
            "verification_status = 'verified', verified_at = ?, "
            "primary_verification_channel = ? WHERE id = ?",
            (
                normalized,
                created_at if created_at is not None else applied_at,
                channel,
                caregiver_id,
            ),
        )
    _inject(failure_injector, "backfill:caregivers")

    connection.execute(CAREGIVER_IDENTITY_INDEX_SQL)
    _inject(failure_injector, f"index:{CAREGIVER_IDENTITY_INDEX}")
    connection.execute(VERIFICATION_TABLE_SQL)
    _inject(failure_injector, f"table:{VERIFICATION_TABLE}")
    connection.execute(ACTIVE_LOOKUP_INDEX_SQL)
    _inject(failure_injector, f"index:{ACTIVE_LOOKUP_INDEX}")
    connection.execute(EXPIRY_INDEX_SQL)
    _inject(failure_injector, f"index:{EXPIRY_INDEX}")
    connection.execute(ACTIVE_CHALLENGE_INDEX_SQL)
    _inject(failure_injector, f"index:{ACTIVE_CHALLENGE_INDEX}")

    if not _table_exists(connection, MIGRATION_TABLE):
        connection.execute(MIGRATION_TABLE_SQL)
        _inject(failure_injector, f"table:{MIGRATION_TABLE}")
    connection.execute(
        f"INSERT INTO {_quote(MIGRATION_TABLE)} "
        "(version, applied_at, source_backup_sha256) VALUES (?, ?, ?)",
        (MIGRATION_VERSION, applied_at, backup_sha256),
    )
    _inject(failure_injector, "marker:row")
    return added_columns, applied_at


def _same_file_if_present(first, second):
    return first.is_file() and second.is_file() and os.path.samefile(first, second)


def _secondary_hash(database_path):
    secondary_path = database_path.with_name(REFUSED_DATABASE_NAME)
    return _sha256_file(secondary_path) if secondary_path.is_file() else None


def migrate_caregiver_verification(
    database_path,
    backup_path,
    *,
    failure_injector=None,
):
    """Apply or verify the idempotent caregiver OTP foundation migration."""

    database_path = Path(database_path).resolve()
    backup_path = Path(backup_path).resolve()
    secondary_path = database_path.with_name(REFUSED_DATABASE_NAME)

    if database_path.name == REFUSED_DATABASE_NAME:
        raise RuntimeError("Refusing to modify eldercare_bd_2.db.")
    if database_path.name != AUTHORITATIVE_DATABASE_NAME:
        raise RuntimeError("Refusing to migrate a non-authoritative database.")
    if backup_path.name == REFUSED_DATABASE_NAME:
        raise RuntimeError("Refusing to use eldercare_bd_2.db as a migration backup.")
    if not database_path.is_file() or not backup_path.is_file():
        raise RuntimeError("Database and verified backup files are required.")
    if database_path == backup_path or os.path.samefile(database_path, backup_path):
        raise RuntimeError("Backup must be a separate file.")
    if _same_file_if_present(database_path, secondary_path):
        raise RuntimeError("Secondary database must be a separate file.")
    if _same_file_if_present(backup_path, secondary_path):
        raise RuntimeError("Refusing a backup alias of eldercare_bd_2.db.")

    _require_no_sidecars(database_path)
    _require_no_sidecars(backup_path)
    database_sha256_before_lock = _sha256_file(database_path)
    database_sha256_before = database_sha256_before_lock
    backup_sha256 = _sha256_file(backup_path)
    secondary_sha256 = _secondary_hash(database_path)

    connection = sqlite3.connect(database_path, timeout=10)
    backup_connection = None
    locked = False
    applied = False
    before_schema = None
    after_schema = None
    before_reference = None
    preserved_values = None
    post_reference = None
    post_values = None
    historical_manifest = ()
    preserved_markers = ()
    added_columns = []
    marker_applied_at = None

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
        database_sha256_before = _sha256_file(database_path)
        if database_sha256_before != database_sha256_before_lock:
            raise RuntimeError("Database changed before the migration lock.")
        if _sha256_file(backup_path) != backup_sha256:
            raise RuntimeError("Verified backup changed before migration.")

        backup_connection = _read_only_connection(backup_path)
        if backup_connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
            raise RuntimeError("Backup WAL mode must be checkpointed first.")
        _validate_integrity(backup_connection)
        _validate_integrity(connection)

        backup_state, _ = _migration_state(backup_connection)
        if backup_state != "unmigrated":
            raise RuntimeError("Backup must be the unmigrated OTP preimage.")
        backup_schema = _schema_snapshot(backup_connection)
        historical_manifest = _historical_manifest(backup_connection)
        backup_reference = _reference_without_markers(backup_schema)
        backup_values = _value_digests(backup_connection, backup_reference)
        backup_markers = _marker_rows(backup_connection)

        before_schema = _schema_snapshot(connection)
        state, marker = _migration_state(connection)
        if state == "partial":
            raise RuntimeError("Partial caregiver OTP migration detected; refusing repair.")
        if state == "unmigrated":
            if database_sha256_before != backup_sha256:
                raise RuntimeError("Backup must be byte-identical before migration.")
            if before_schema != backup_schema:
                raise RuntimeError("Backup and live schema snapshots differ.")
            if _value_digests(connection, backup_reference) != backup_values:
                raise RuntimeError("Backup and live typed values differ.")
            if _marker_rows(connection) != backup_markers:
                raise RuntimeError("Backup and live migration markers differ.")
        else:
            if marker[2] != backup_sha256:
                raise RuntimeError("Migration marker does not match this backup.")
            _verify_expected_schema(connection, backup_schema)
            _verify_marker(connection, backup_sha256)

        before_reference = _reference_without_markers(before_schema)
        preserved_values = _value_digests(connection, before_reference)
        preserved_markers = _marker_rows(connection, exclude_current=True)

        if state == "unmigrated":
            added_columns, marker_applied_at = _apply_migration(
                connection,
                historical_manifest,
                backup_sha256,
                failure_injector,
            )
            applied = True
            if connection.execute(
                f"SELECT COUNT(*) FROM {_quote(VERIFICATION_TABLE)}"
            ).fetchone()[0] != 0:
                raise RuntimeError("The new verification table must start empty.")
        else:
            marker_applied_at = marker[1]

        after_schema = _verify_expected_schema(connection, backup_schema)
        _verify_marker(connection, backup_sha256)
        if _marker_rows(connection, exclude_current=True) != preserved_markers:
            raise RuntimeError("Pre-existing migration markers changed.")
        if _value_digests(connection, before_reference) != preserved_values:
            raise RuntimeError("Pre-existing IDs or typed values changed.")
        _verify_historical_backfill(
            connection,
            historical_manifest,
            marker_applied_at,
        )
        _validate_integrity(connection)

        post_reference = _reference_without_markers(after_schema)
        post_values = _value_digests(connection, post_reference)
        connection.commit()
        locked = False
    except Exception as exc:
        if locked:
            connection.rollback()
        if backup_connection is not None:
            backup_connection.close()
        connection.close()
        _require_no_sidecars(database_path)
        if _sha256_file(database_path) != database_sha256_before:
            raise RuntimeError(
                "Migration rollback did not restore the exact database bytes."
            ) from exc
        if _sha256_file(backup_path) != backup_sha256:
            raise RuntimeError("Verified backup changed during migration.") from exc
        if _secondary_hash(database_path) != secondary_sha256:
            raise RuntimeError("Secondary database changed during migration.") from exc
        raise
    else:
        if backup_connection is not None:
            backup_connection.close()
        connection.close()

    _require_no_sidecars(database_path)
    _require_no_sidecars(backup_path)
    if _sha256_file(backup_path) != backup_sha256:
        raise RuntimeError("Verified backup changed during migration.")
    if _secondary_hash(database_path) != secondary_sha256:
        raise RuntimeError("Secondary database changed during migration.")

    reopened = _read_only_connection(database_path)
    try:
        _validate_integrity(reopened)
        reopened_schema = _verify_expected_schema(reopened, backup_schema)
        if reopened_schema != after_schema:
            raise RuntimeError("Committed schema differs after reopen.")
        _verify_marker(reopened, backup_sha256)
        if _marker_rows(reopened, exclude_current=True) != preserved_markers:
            raise RuntimeError("Committed pre-existing markers changed.")
        if _value_digests(reopened, before_reference) != preserved_values:
            raise RuntimeError("Committed pre-existing values changed.")
        if _value_digests(reopened, post_reference) != post_values:
            raise RuntimeError("Committed full values changed after reopen.")
        _verify_historical_backfill(
            reopened,
            historical_manifest,
            marker_applied_at,
        )
    finally:
        reopened.close()

    database_sha256_after = _sha256_file(database_path)
    if not applied and database_sha256_after != database_sha256_before:
        raise RuntimeError("Completed migration rerun was not a byte-for-byte no-op.")

    identity_counts = {"email": 0, "sms": 0, "legacy_unclassified": 0}
    for _caregiver_id, normalized, channel, _created_at in historical_manifest:
        if normalized is None:
            identity_counts["legacy_unclassified"] += 1
        else:
            identity_counts[channel] += 1

    return {
        "migration_version": MIGRATION_VERSION,
        "applied": applied,
        "database": database_path.name,
        "backup_sha256": backup_sha256,
        "database_sha256_before": database_sha256_before,
        "database_sha256_after": database_sha256_after,
        "schema_sha256_before": _snapshot_digest(before_schema),
        "schema_sha256_after": _snapshot_digest(after_schema),
        "historical_caregiver_count": len(historical_manifest),
        "historical_identity_counts": identity_counts,
        "historical_caregivers_verified": True,
        "preexisting_ids_and_typed_values_preserved": True,
        "added_caregiver_columns": added_columns,
        "created_table": VERIFICATION_TABLE if applied else None,
        "created_indexes": (
            [
                CAREGIVER_IDENTITY_INDEX,
                ACTIVE_LOOKUP_INDEX,
                EXPIRY_INDEX,
                ACTIVE_CHALLENGE_INDEX,
            ]
            if applied
            else []
        ),
        "integrity": "ok",
        "foreign_key_issues": 0,
        "backup_unchanged": True,
        "secondary_database_unchanged": True,
    }

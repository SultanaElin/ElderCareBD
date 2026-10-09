import hashlib
import json
import os
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path


AUTHORITATIVE_DATABASE_NAME = "eldercare_bd.db"
REFUSED_DATABASE_NAME = "eldercare_bd_2.db"
MIGRATION_VERSION = "task14_ml_prediction_provenance_v1"
MIGRATION_TABLE = "eldercare_schema_migrations"

ASSESSMENT_ML_COLUMNS = {
    "diabetes_prediction_source": "VARCHAR",
    "diabetes_prediction_status": "VARCHAR",
    "diabetes_model_version": "VARCHAR",
    "diabetes_model_score": "FLOAT",
    "diabetes_model_threshold": "FLOAT",
    "diabetes_model_classification": "VARCHAR",
    "diabetes_ogtt_glucose": "FLOAT",
    "heart_prediction_source": "VARCHAR",
    "heart_prediction_status": "VARCHAR",
    "heart_model_version": "VARCHAR",
    "heart_model_score": "FLOAT",
    "heart_model_threshold": "FLOAT",
    "heart_model_classification": "VARCHAR",
    "heart_clinical_sex": "VARCHAR",
    "heart_chest_pain_type": "VARCHAR",
    "heart_resting_systolic_bp": "INTEGER",
}

MIGRATION_TABLE_SQL = f"""
    CREATE TABLE {MIGRATION_TABLE} (
        version TEXT PRIMARY KEY NOT NULL,
        applied_at TEXT NOT NULL,
        source_backup_sha256 TEXT NOT NULL
    )
"""


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sidecar_paths(database_path):
    return tuple(
        Path(f"{database_path}{suffix}")
        for suffix in ("-wal", "-shm", "-journal")
    )


def _require_no_sidecars(database_path):
    if any(path.exists() for path in _sidecar_paths(database_path)):
        raise RuntimeError(
            "SQLite WAL, shared-memory, or journal sidecars must be resolved "
            "before migration."
        )


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _normalize_sql(value):
    if value is None:
        return None
    normalized = " ".join(value.strip().split()).rstrip(";").lower()
    return normalized.replace(" if not exists ", " ")


def _table_exists(connection, table_name):
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def _column_snapshot(connection, table_name):
    return tuple(
        {
            "cid": row[0],
            "name": row[1],
            "type": (row[2] or "").upper(),
            "notnull": row[3],
            "default": row[4],
            "pk": row[5],
        }
        for row in connection.execute(
            f"PRAGMA table_info({_quote(table_name)})"
        ).fetchall()
    )


def _foreign_key_snapshot(connection, table_name):
    return tuple(
        tuple(row)
        for row in connection.execute(
            f"PRAGMA foreign_key_list({_quote(table_name)})"
        ).fetchall()
    )


def _index_snapshot(connection, table_name):
    indexes = []
    rows = connection.execute(
        f"PRAGMA index_list({_quote(table_name)})"
    ).fetchall()
    for row in sorted(rows, key=lambda value: value[1]):
        index_name = row[1]
        columns = tuple(
            tuple(index_row)
            for index_row in connection.execute(
                f"PRAGMA index_info({_quote(index_name)})"
            ).fetchall()
        )
        indexes.append((tuple(row), columns))
    return tuple(indexes)


def _schema_snapshot(connection):
    objects = tuple(
        (row[0], row[1], row[2], _normalize_sql(row[3]))
        for row in connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE type IN ('table', 'index', 'trigger', 'view')
            ORDER BY type, name
            """
        ).fetchall()
    )
    table_names = [
        row[0]
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    ]
    tables = {
        table_name: {
            "columns": _column_snapshot(connection, table_name),
            "foreign_keys": _foreign_key_snapshot(connection, table_name),
            "indexes": _index_snapshot(connection, table_name),
        }
        for table_name in table_names
    }
    return {"objects": objects, "tables": tables}


def _snapshot_digest(snapshot):
    encoded = json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _encode_digest_value(digest, value):
    if value is None:
        tag, payload = b"N", b""
    elif isinstance(value, bytes):
        tag, payload = b"B", value
    elif isinstance(value, bool):
        tag, payload = b"T", b"1" if value else b"0"
    elif isinstance(value, int):
        tag, payload = b"I", str(value).encode("ascii")
    elif isinstance(value, float):
        tag, payload = b"F", struct.pack(">d", value)
    else:
        tag, payload = b"S", str(value).encode("utf-8")
    digest.update(tag)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def _value_reference(schema_snapshot):
    return {
        table_name: tuple(column["name"] for column in details["columns"])
        for table_name, details in schema_snapshot["tables"].items()
    }


def _value_digests(
    connection,
    reference_columns,
    *,
    exclude_task14_marker=False,
):
    result = {}
    for table_name in sorted(reference_columns):
        columns = reference_columns[table_name]
        if not columns or not _table_exists(connection, table_name):
            raise RuntimeError("A snapshotted table or column is missing.")

        column_details = _column_snapshot(connection, table_name)
        current_names = {column["name"] for column in column_details}
        if not set(columns).issubset(current_names):
            raise RuntimeError("A snapshotted table or column is missing.")

        primary_keys = tuple(
            column["name"]
            for column in sorted(
                (column for column in column_details if column["pk"]),
                key=lambda column: column["pk"],
            )
        )
        order_columns = primary_keys or columns
        selected = ", ".join(_quote(column) for column in columns)
        ordering = ", ".join(_quote(column) for column in order_columns)
        where_clause = ""
        parameters = ()
        if table_name == MIGRATION_TABLE and exclude_task14_marker:
            where_clause = " WHERE version <> ?"
            parameters = (MIGRATION_VERSION,)
        rows = connection.execute(
            f"SELECT {selected} FROM {_quote(table_name)}"
            f"{where_clause} ORDER BY {ordering}",
            parameters,
        ).fetchall()

        digest = hashlib.sha256()
        _encode_digest_value(digest, table_name)
        for column in columns:
            _encode_digest_value(digest, column)
        for row in rows:
            digest.update(b"R")
            for value in row:
                _encode_digest_value(digest, value)
        result[table_name] = {
            "row_count": len(rows),
            "sha256": digest.hexdigest(),
        }
    return result


def _validate_integrity(connection):
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("SQLite integrity_check failed.")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("SQLite foreign_key_check failed.")


def _expected_marker_columns():
    return (
        {
            "cid": 0,
            "name": "version",
            "type": "TEXT",
            "notnull": 1,
            "default": None,
            "pk": 1,
        },
        {
            "cid": 1,
            "name": "applied_at",
            "type": "TEXT",
            "notnull": 1,
            "default": None,
            "pk": 0,
        },
        {
            "cid": 2,
            "name": "source_backup_sha256",
            "type": "TEXT",
            "notnull": 1,
            "default": None,
            "pk": 0,
        },
    )


def _validate_marker_table(connection):
    if not _table_exists(connection, MIGRATION_TABLE):
        return
    if _column_snapshot(connection, MIGRATION_TABLE) != _expected_marker_columns():
        raise RuntimeError("Migration marker schema is invalid.")
    table_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (MIGRATION_TABLE,),
    ).fetchone()[0]
    if _normalize_sql(table_sql) != _normalize_sql(MIGRATION_TABLE_SQL):
        raise RuntimeError("Migration marker table declaration is invalid.")


def _migration_state(connection):
    if not _table_exists(connection, "assessments"):
        raise RuntimeError("The assessments table is required for this migration.")
    assessment_names = {
        column["name"] for column in _column_snapshot(connection, "assessments")
    }
    present_columns = set(ASSESSMENT_ML_COLUMNS).intersection(assessment_names)

    _validate_marker_table(connection)
    marker = None
    if _table_exists(connection, MIGRATION_TABLE):
        marker = connection.execute(
            f"""
            SELECT version, source_backup_sha256
            FROM {_quote(MIGRATION_TABLE)} WHERE version = ?
            """,
            (MIGRATION_VERSION,),
        ).fetchone()

    complete_columns = set(ASSESSMENT_ML_COLUMNS).issubset(assessment_names)
    if marker is not None and complete_columns:
        return "complete", marker
    if marker is None and not present_columns:
        return "unmigrated", None
    return "partial", marker


def _expected_column(column_name, column_type, cid):
    return {
        "cid": cid,
        "name": column_name,
        "type": column_type.upper(),
        "notnull": 0,
        "default": None,
        "pk": 0,
    }


def _object_set(schema_snapshot, object_type, *, exclude_marker=False):
    return {
        (row[1], row[2], row[3])
        for row in schema_snapshot["objects"]
        if row[0] == object_type
        and not (exclude_marker and row[2] == MIGRATION_TABLE)
    }


def _verify_expected_schema(current, backup):
    backup_tables = backup["tables"]
    current_tables = current["tables"]
    expected_table_names = set(backup_tables)
    expected_table_names.add(MIGRATION_TABLE)
    if set(current_tables) != expected_table_names:
        raise RuntimeError("Unexpected table set after migration.")

    for table_name, backup_details in backup_tables.items():
        current_details = current_tables.get(table_name)
        if current_details is None:
            raise RuntimeError("A pre-existing table disappeared during migration.")

        expected_columns = list(backup_details["columns"])
        if table_name == "assessments":
            for column_name, column_type in ASSESSMENT_ML_COLUMNS.items():
                expected_columns.append(
                    _expected_column(column_name, column_type, len(expected_columns))
                )
        if tuple(expected_columns) != current_details["columns"]:
            raise RuntimeError("Column declarations do not match the expected schema.")
        if backup_details["foreign_keys"] != current_details["foreign_keys"]:
            raise RuntimeError("Foreign-key declarations changed during migration.")
        if backup_details["indexes"] != current_details["indexes"]:
            raise RuntimeError("Existing indexes changed during migration.")

    marker_columns = current_tables[MIGRATION_TABLE]["columns"]
    if marker_columns != _expected_marker_columns():
        raise RuntimeError("Migration marker schema is invalid.")

    backup_table_sql = {
        row[1]: row[3] for row in backup["objects"] if row[0] == "table"
    }
    current_table_sql = {
        row[1]: row[3] for row in current["objects"] if row[0] == "table"
    }
    for table_name, table_sql in backup_table_sql.items():
        if table_name != "assessments":
            if current_table_sql.get(table_name) != table_sql:
                raise RuntimeError("A pre-existing table declaration changed.")
    if current_table_sql.get(MIGRATION_TABLE) != _normalize_sql(
        MIGRATION_TABLE_SQL
    ):
        raise RuntimeError("Migration marker table declaration is invalid.")

    for object_type in ("trigger", "view"):
        if _object_set(current, object_type) != _object_set(backup, object_type):
            raise RuntimeError(
                f"Existing {object_type} definitions changed during migration."
            )

    marker_was_created = MIGRATION_TABLE not in backup_tables
    if _object_set(
        current,
        "index",
        exclude_marker=marker_was_created,
    ) != _object_set(backup, "index"):
        raise RuntimeError("Existing index definitions changed during migration.")


def _historical_assessment_ids(connection):
    if not _table_exists(connection, "assessments"):
        raise RuntimeError("The backup has no assessments table.")
    columns = {column["name"] for column in _column_snapshot(connection, "assessments")}
    if "id" not in columns:
        raise RuntimeError("The assessments table has no id column.")
    return tuple(
        row[0]
        for row in connection.execute(
            "SELECT id FROM assessments ORDER BY id"
        ).fetchall()
    )


def _verify_historical_assessment_nulls(connection, historical_ids):
    if not historical_ids:
        return
    placeholders = ", ".join("?" for _ in historical_ids)
    matching_count = connection.execute(
        f"SELECT COUNT(*) FROM assessments WHERE id IN ({placeholders})",
        historical_ids,
    ).fetchone()[0]
    if matching_count != len(historical_ids):
        raise RuntimeError("A historical assessment disappeared during migration.")

    non_null_predicates = " OR ".join(
        f"{_quote(column_name)} IS NOT NULL"
        for column_name in ASSESSMENT_ML_COLUMNS
    )
    non_null_count = connection.execute(
        f"""
        SELECT COUNT(*) FROM assessments
        WHERE id IN ({placeholders}) AND ({non_null_predicates})
        """,
        historical_ids,
    ).fetchone()[0]
    if non_null_count:
        raise RuntimeError(
            "Historical assessment ML provenance columns must remain NULL."
        )


def _verify_marker(connection, backup_sha256):
    rows = connection.execute(
        f"""
        SELECT version, source_backup_sha256
        FROM {_quote(MIGRATION_TABLE)} WHERE version = ?
        """,
        (MIGRATION_VERSION,),
    ).fetchall()
    if rows != [(MIGRATION_VERSION, backup_sha256)]:
        raise RuntimeError("Migration marker verification failed.")


def _inject(failure_injector, step):
    if failure_injector is not None:
        failure_injector(step)


def _apply_migration(connection, backup_sha256, failure_injector):
    added_columns = []
    for column_name, column_type in ASSESSMENT_ML_COLUMNS.items():
        connection.execute(
            f"ALTER TABLE assessments ADD COLUMN "
            f"{_quote(column_name)} {column_type}"
        )
        added_columns.append(column_name)
        _inject(failure_injector, f"column:assessments.{column_name}")

    if not _table_exists(connection, MIGRATION_TABLE):
        connection.execute(MIGRATION_TABLE_SQL)
    _inject(failure_injector, "marker:table")
    connection.execute(
        f"""
        INSERT INTO {_quote(MIGRATION_TABLE)} (
            version, applied_at, source_backup_sha256
        ) VALUES (?, ?, ?)
        """,
        (
            MIGRATION_VERSION,
            datetime.now(timezone.utc).isoformat(),
            backup_sha256,
        ),
    )
    _inject(failure_injector, "marker:row")
    return added_columns


def _read_only_connection(path):
    connection = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA query_only = ON")
    return connection


def _same_file_if_present(first, second):
    return first.is_file() and second.is_file() and os.path.samefile(first, second)


def migrate_assessment_ml(database_path, backup_path, *, failure_injector=None):
    database_path = Path(database_path).resolve()
    backup_path = Path(backup_path).resolve()
    secondary_path = database_path.with_name(REFUSED_DATABASE_NAME)

    if database_path.name == REFUSED_DATABASE_NAME:
        raise RuntimeError("Refusing to modify eldercare_bd_2.db.")
    if database_path.name != AUTHORITATIVE_DATABASE_NAME:
        raise RuntimeError(
            f"Refusing to migrate non-authoritative database: {database_path.name}"
        )
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
    secondary_sha256 = (
        _sha256_file(secondary_path) if secondary_path.is_file() else None
    )

    connection = sqlite3.connect(database_path, timeout=10)
    backup_connection = None
    locked = False
    applied = False
    pre_schema = None
    post_schema = None
    preserved_digests = None
    post_full_digests = None
    before_reference = None
    post_reference = None
    historical_ids = ()
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
        database_sha256_before = _sha256_file(database_path)
        if database_sha256_before != database_sha256_before_lock:
            raise RuntimeError(
                "Database changed before the migration lock was acquired."
            )
        if _sha256_file(backup_path) != backup_sha256:
            raise RuntimeError("Verified backup changed before migration preflight.")

        backup_connection = _read_only_connection(backup_path)
        if (
            backup_connection.execute("PRAGMA journal_mode").fetchone()[0].lower()
            == "wal"
        ):
            raise RuntimeError(
                "Backup WAL mode must be checkpointed and disabled first."
            )
        _validate_integrity(backup_connection)
        _validate_integrity(connection)
        backup_state, _ = _migration_state(backup_connection)
        if backup_state != "unmigrated":
            raise RuntimeError("Backup must be the unmigrated database preimage.")

        backup_schema = _schema_snapshot(backup_connection)
        pre_schema = _schema_snapshot(connection)
        state, marker = _migration_state(connection)
        if state == "partial":
            raise RuntimeError(
                "Partial assessment ML migration detected; refusing repair."
            )

        historical_ids = _historical_assessment_ids(backup_connection)
        backup_reference = _value_reference(backup_schema)
        backup_digests = _value_digests(
            backup_connection,
            backup_reference,
            exclude_task14_marker=True,
        )
        if state == "unmigrated":
            if database_sha256_before != backup_sha256:
                raise RuntimeError("Backup must be byte-identical before migration.")
            if pre_schema != backup_schema:
                raise RuntimeError("Backup and live schema snapshots differ.")
            preserved_digests = _value_digests(
                connection,
                backup_reference,
                exclude_task14_marker=True,
            )
            if backup_digests != preserved_digests:
                raise RuntimeError("Backup and live value snapshots differ.")
        else:
            if marker[1] != backup_sha256:
                raise RuntimeError("Migration marker does not match this backup.")
            _verify_expected_schema(pre_schema, backup_schema)
            _verify_marker(connection, backup_sha256)

        before_reference = _value_reference(pre_schema)
        preserved_digests = _value_digests(
            connection,
            before_reference,
            exclude_task14_marker=True,
        )

        if state == "unmigrated":
            added_columns = _apply_migration(
                connection,
                backup_sha256,
                failure_injector,
            )
            applied = True

        post_schema = _schema_snapshot(connection)
        _verify_expected_schema(post_schema, backup_schema)
        _verify_marker(connection, backup_sha256)
        _validate_integrity(connection)
        if _value_digests(
            connection,
            before_reference,
            exclude_task14_marker=True,
        ) != preserved_digests:
            raise RuntimeError("Pre-existing IDs or typed values changed.")
        _verify_historical_assessment_nulls(connection, historical_ids)

        post_reference = _value_reference(post_schema)
        post_full_digests = _value_digests(connection, post_reference)
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
        current_secondary_sha256 = (
            _sha256_file(secondary_path) if secondary_path.is_file() else None
        )
        if secondary_sha256 != current_secondary_sha256:
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
    current_secondary_sha256 = (
        _sha256_file(secondary_path) if secondary_path.is_file() else None
    )
    if secondary_sha256 != current_secondary_sha256:
        raise RuntimeError("Secondary database changed during migration.")

    reopened = _read_only_connection(database_path)
    try:
        _validate_integrity(reopened)
        reopened_schema = _schema_snapshot(reopened)
        if reopened_schema != post_schema:
            raise RuntimeError("Committed schema snapshot differs after reopen.")
        _verify_expected_schema(reopened_schema, backup_schema)
        _verify_marker(reopened, backup_sha256)
        if _value_digests(
            reopened,
            before_reference,
            exclude_task14_marker=True,
        ) != preserved_digests:
            raise RuntimeError("Committed pre-existing values changed.")
        if _value_digests(reopened, post_reference) != post_full_digests:
            raise RuntimeError("Committed full value snapshot differs after reopen.")
        _verify_historical_assessment_nulls(reopened, historical_ids)
    finally:
        reopened.close()

    database_sha256_after = _sha256_file(database_path)
    if not applied and database_sha256_after != database_sha256_before:
        raise RuntimeError("A completed migration rerun was not a byte-for-byte no-op.")

    return {
        "migration_version": MIGRATION_VERSION,
        "applied": applied,
        "database": database_path.name,
        "backup_sha256": backup_sha256,
        "database_sha256_before": database_sha256_before,
        "database_sha256_after": database_sha256_after,
        "schema_sha256_before": _snapshot_digest(pre_schema),
        "schema_sha256_after": _snapshot_digest(post_schema),
        "record_counts": {
            table_name: details["row_count"]
            for table_name, details in preserved_digests.items()
        },
        "preexisting_value_digests": {
            table_name: details["sha256"]
            for table_name, details in preserved_digests.items()
        },
        "record_ids_and_typed_values_preserved": True,
        "historical_assessment_count": len(historical_ids),
        "historical_assessment_ml_values_null": True,
        "foreign_key_issues": 0,
        "added_assessment_columns": added_columns,
        "backup_unchanged": True,
        "secondary_database_unchanged": True,
    }

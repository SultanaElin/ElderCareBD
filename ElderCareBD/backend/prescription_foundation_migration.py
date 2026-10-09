import hashlib
import json
import os
import re
import sqlite3
import struct
import warnings
from datetime import datetime, timezone
from pathlib import Path

from image_storage import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_HEIGHT,
    MAX_IMAGE_PIXELS,
    MAX_IMAGE_WIDTH,
)
from prescription_integrity import MEDICINE_PRESCRIPTION_TRIGGER_SQL


AUTHORITATIVE_DATABASE_NAME = "eldercare_bd.db"
REFUSED_DATABASE_NAME = "eldercare_bd_2.db"
MIGRATION_VERSION = "task12a_secure_prescription_foundation_v2"
MIGRATION_TABLE = "eldercare_schema_migrations"

PRESCRIPTION_COLUMNS = {
    "image_original_name": "VARCHAR",
    "image_mime_type": "VARCHAR",
    "image_size_bytes": "INTEGER",
    "image_sha256": "VARCHAR(64)",
    "ocr_text": "TEXT",
    "ocr_status": "VARCHAR",
    "ocr_engine": "VARCHAR",
    "ocr_error": "TEXT",
    "confirmed_at": "DATETIME",
    "confirmation_hash": "VARCHAR(64)",
}
MEDICINE_COLUMNS = {
    "strength": "VARCHAR",
    "duration": "VARCHAR",
    "instructions": "TEXT",
}
MIGRATION_TABLE_SQL = f"""
    CREATE TABLE {MIGRATION_TABLE} (
        version TEXT PRIMARY KEY NOT NULL,
        applied_at TEXT NOT NULL,
        source_backup_sha256 TEXT NOT NULL
    )
"""

_PRIVATE_IMAGE_KEY = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png)$")
_IMAGE_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png"}


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
    for row in connection.execute(
        f"PRAGMA index_list({_quote(table_name)})"
    ).fetchall():
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
        (
            row[0],
            row[1],
            row[2],
            _normalize_sql(row[3]),
        )
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


def _value_digests(connection, reference_columns):
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
        rows = connection.execute(
            f"SELECT {selected} FROM {_quote(table_name)} ORDER BY {ordering}"
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


def _ownership_violation_count(connection):
    queries = (
        """
        SELECT COUNT(*) FROM patients p
        LEFT JOIN caregivers c ON c.id = p.caregiver_id
        WHERE c.id IS NULL
        """,
        """
        SELECT COUNT(*) FROM prescriptions p
        LEFT JOIN patients owner ON owner.id = p.patient_id
        WHERE owner.id IS NULL
        """,
        """
        SELECT COUNT(*) FROM medicines m
        LEFT JOIN patients owner ON owner.id = m.patient_id
        WHERE owner.id IS NULL
        """,
        """
        SELECT COUNT(*) FROM medicines m
        LEFT JOIN prescriptions p ON p.id = m.prescription_id
        WHERE m.prescription_id IS NOT NULL AND p.id IS NULL
        """,
        """
        SELECT COUNT(*) FROM medicines m
        JOIN prescriptions p ON p.id = m.prescription_id
        WHERE m.patient_id <> p.patient_id
        """,
    )
    total = sum(connection.execute(query).fetchone()[0] for query in queries)
    if _table_exists(connection, "assessments"):
        total += connection.execute(
            """
            SELECT COUNT(*) FROM assessments a
            LEFT JOIN patients owner ON owner.id = a.patient_id
            WHERE owner.id IS NULL
            """
        ).fetchone()[0]
    return total


def _resolve_image(database_path, stored_path):
    normalized = stored_path.replace("\\", "/")
    parts = Path(normalized).parts
    if len(parts) == 1 and _PRIVATE_IMAGE_KEY.fullmatch(parts[0]):
        root = (database_path.parent / "private_uploads").resolve()
        candidate = (root / parts[0]).resolve()
    elif (
        len(parts) == 2
        and parts[0] == "uploads"
        and Path(parts[1]).name == parts[1]
    ):
        root = (database_path.parent / "uploads").resolve()
        candidate = (root / parts[1]).resolve()
    else:
        return None
    if candidate.parent != root:
        return None
    return candidate


def _decode_image(path):
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise RuntimeError(
            "Install the bounded Pillow dependency before running this migration."
        ) from exc

    file_size = path.stat().st_size
    if file_size <= 0 or file_size > MAX_IMAGE_BYTES:
        raise RuntimeError("A historical prescription image violates the byte limit.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as verification_image:
                image_format = verification_image.format
                dimensions = verification_image.size
                if image_format not in _IMAGE_FORMATS:
                    raise RuntimeError("A historical prescription image is unsupported.")
                width, height = dimensions
                if (
                    width <= 0
                    or height <= 0
                    or width > MAX_IMAGE_WIDTH
                    or height > MAX_IMAGE_HEIGHT
                    or width * height > MAX_IMAGE_PIXELS
                ):
                    raise RuntimeError(
                        "A historical prescription image violates the pixel limit."
                    )
                verification_image.verify()

            with Image.open(path) as decoded_image:
                if (
                    decoded_image.format != image_format
                    or decoded_image.size != dimensions
                ):
                    raise RuntimeError("A historical prescription image is malformed.")
                decoded_image.load()
    except RuntimeError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise RuntimeError(
            "A historical prescription image could not be fully decoded."
        ) from exc

    return {
        "mime_type": _IMAGE_FORMATS[image_format],
        "size_bytes": file_size,
        "sha256": _sha256_file(path),
        "width": dimensions[0],
        "height": dimensions[1],
        "format": image_format,
    }


def _image_manifest(connection, database_path):
    manifest = {}
    rows = connection.execute(
        """
        SELECT id, image_path FROM prescriptions
        WHERE image_path IS NOT NULL AND TRIM(image_path) <> ''
        ORDER BY id
        """
    ).fetchall()
    for prescription_id, stored_path in rows:
        resolved = _resolve_image(database_path, stored_path)
        if resolved is None or not resolved.is_file():
            raise RuntimeError(
                "A historical prescription image is missing or outside storage."
            )
        metadata = _decode_image(resolved)
        metadata["stored_path_sha256"] = hashlib.sha256(
            stored_path.encode("utf-8")
        ).hexdigest()
        manifest[str(prescription_id)] = metadata
    return manifest


def _manifest_summary(manifest):
    return {
        "count": len(manifest),
        "sha256": _snapshot_digest(manifest),
    }


def _trigger_snapshot(connection):
    return {
        row[0]: _normalize_sql(row[1])
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name"
        ).fetchall()
    }


def _migration_state(connection):
    prescription_names = {
        column["name"] for column in _column_snapshot(connection, "prescriptions")
    }
    medicine_names = {
        column["name"] for column in _column_snapshot(connection, "medicines")
    }
    trigger_names = set(_trigger_snapshot(connection))
    present_features = (
        set(PRESCRIPTION_COLUMNS).intersection(prescription_names)
        | set(MEDICINE_COLUMNS).intersection(medicine_names)
        | set(MEDICINE_PRESCRIPTION_TRIGGER_SQL).intersection(trigger_names)
    )

    marker_present = _table_exists(connection, MIGRATION_TABLE)
    marker = None
    if marker_present:
        marker = connection.execute(
            f"""
            SELECT version, source_backup_sha256
            FROM {_quote(MIGRATION_TABLE)} WHERE version = ?
            """,
            (MIGRATION_VERSION,),
        ).fetchone()

    complete_features = (
        set(PRESCRIPTION_COLUMNS).issubset(prescription_names)
        and set(MEDICINE_COLUMNS).issubset(medicine_names)
        and set(MEDICINE_PRESCRIPTION_TRIGGER_SQL).issubset(trigger_names)
    )
    if marker is not None and complete_features:
        return "complete", marker
    if not marker_present and not present_features:
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


def _verify_expected_schema(current, backup):
    backup_tables = backup["tables"]
    current_tables = current["tables"]
    if set(current_tables) != set(backup_tables) | {MIGRATION_TABLE}:
        raise RuntimeError("Unexpected table set after migration.")

    for table_name, backup_details in backup_tables.items():
        current_details = current_tables.get(table_name)
        if current_details is None:
            raise RuntimeError("A pre-existing table disappeared during migration.")

        expected_columns = list(backup_details["columns"])
        additions = None
        if table_name == "prescriptions":
            additions = PRESCRIPTION_COLUMNS
        elif table_name == "medicines":
            additions = MEDICINE_COLUMNS
        if additions is not None:
            for column_name, column_type in additions.items():
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
    expected_marker_columns = (
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
    if marker_columns != expected_marker_columns:
        raise RuntimeError("Migration marker schema is invalid.")

    backup_table_sql = {
        row[1]: row[3] for row in backup["objects"] if row[0] == "table"
    }
    current_table_sql = {
        row[1]: row[3] for row in current["objects"] if row[0] == "table"
    }
    for table_name, table_sql in backup_table_sql.items():
        if table_name not in {"prescriptions", "medicines"}:
            if current_table_sql.get(table_name) != table_sql:
                raise RuntimeError("A pre-existing table declaration changed.")
    if current_table_sql.get(MIGRATION_TABLE) != _normalize_sql(MIGRATION_TABLE_SQL):
        raise RuntimeError("Migration marker table declaration is invalid.")

    backup_triggers = {
        name: sql
        for name, sql in (
            (row[1], row[3])
            for row in backup["objects"]
            if row[0] == "trigger"
        )
    }
    current_triggers = {
        name: sql
        for name, sql in (
            (row[1], row[3])
            for row in current["objects"]
            if row[0] == "trigger"
        )
    }
    expected_triggers = dict(backup_triggers)
    expected_triggers.update(
        {
            name: _normalize_sql(sql)
            for name, sql in MEDICINE_PRESCRIPTION_TRIGGER_SQL.items()
        }
    )
    if current_triggers != expected_triggers:
        raise RuntimeError("Trigger definitions do not match the expected schema.")

    backup_indexes = {
        (row[1], row[2], row[3])
        for row in backup["objects"]
        if row[0] == "index"
    }
    current_existing_indexes = {
        (row[1], row[2], row[3])
        for row in current["objects"]
        if row[0] == "index" and row[2] != MIGRATION_TABLE
    }
    if current_existing_indexes != backup_indexes:
        raise RuntimeError("Index definitions changed during migration.")

    backup_views = {
        (row[1], row[2], row[3])
        for row in backup["objects"]
        if row[0] == "view"
    }
    current_views = {
        (row[1], row[2], row[3])
        for row in current["objects"]
        if row[0] == "view"
    }
    if current_views != backup_views:
        raise RuntimeError("View definitions changed during migration.")


def _verify_image_metadata(connection, manifest):
    for raw_id, expected in manifest.items():
        row = connection.execute(
            """
            SELECT image_mime_type, image_size_bytes, image_sha256
            FROM prescriptions WHERE id = ?
            """,
            (int(raw_id),),
        ).fetchone()
        if row != (
            expected["mime_type"],
            expected["size_bytes"],
            expected["sha256"],
        ):
            raise RuntimeError("Prescription image metadata verification failed.")


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


def _apply_migration(connection, image_manifest, backup_sha256, failure_injector):
    added_prescription_columns = []
    for column_name, column_type in PRESCRIPTION_COLUMNS.items():
        connection.execute(
            f"ALTER TABLE prescriptions ADD COLUMN {_quote(column_name)} {column_type}"
        )
        added_prescription_columns.append(column_name)
        _inject(failure_injector, f"column:prescriptions.{column_name}")

    added_medicine_columns = []
    for column_name, column_type in MEDICINE_COLUMNS.items():
        connection.execute(
            f"ALTER TABLE medicines ADD COLUMN {_quote(column_name)} {column_type}"
        )
        added_medicine_columns.append(column_name)
        _inject(failure_injector, f"column:medicines.{column_name}")

    for trigger_name, trigger_sql in MEDICINE_PRESCRIPTION_TRIGGER_SQL.items():
        connection.execute(trigger_sql)
        _inject(failure_injector, f"trigger:{trigger_name}")

    connection.execute(MIGRATION_TABLE_SQL)
    _inject(failure_injector, "marker:table")

    for sequence, (raw_id, metadata) in enumerate(image_manifest.items(), start=1):
        connection.execute(
            """
            UPDATE prescriptions
            SET image_mime_type = ?, image_size_bytes = ?, image_sha256 = ?
            WHERE id = ?
            """,
            (
                metadata["mime_type"],
                metadata["size_bytes"],
                metadata["sha256"],
                int(raw_id),
            ),
        )
        _inject(failure_injector, f"image_metadata:{sequence}")

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
    return added_prescription_columns, added_medicine_columns


def _read_only_connection(path):
    connection = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA query_only = ON")
    return connection


def migrate_prescription_foundation(
    database_path,
    backup_path,
    *,
    failure_injector=None,
):
    database_path = Path(database_path).resolve()
    backup_path = Path(backup_path).resolve()
    secondary_path = database_path.with_name(REFUSED_DATABASE_NAME)

    if database_path.name == REFUSED_DATABASE_NAME:
        raise RuntimeError("Refusing to modify eldercare_bd_2.db.")
    if database_path.name != AUTHORITATIVE_DATABASE_NAME:
        raise RuntimeError(
            f"Refusing to migrate non-authoritative database: {database_path.name}"
        )
    if not database_path.is_file() or not backup_path.is_file():
        raise RuntimeError("Database and verified backup files are required.")
    if database_path == backup_path or os.path.samefile(database_path, backup_path):
        raise RuntimeError("Backup must be a separate file.")
    if secondary_path.is_file() and os.path.samefile(database_path, secondary_path):
        raise RuntimeError("Secondary database must be a separate file.")

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
    before_full_digests = None
    preexisting_digests = None
    pre_schema = None
    post_schema = None
    image_manifest = None
    added_prescription_columns = []
    added_medicine_columns = []

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
            raise RuntimeError("Database changed before the migration lock was acquired.")
        if _sha256_file(backup_path) != backup_sha256:
            raise RuntimeError("Verified backup changed before migration preflight.")

        backup_connection = _read_only_connection(backup_path)
        _validate_integrity(backup_connection)
        _validate_integrity(connection)
        if _ownership_violation_count(connection):
            raise RuntimeError(
                "Ownership or patient/prescription relationship preflight failed."
            )

        backup_schema = _schema_snapshot(backup_connection)
        pre_schema = _schema_snapshot(connection)
        state, marker = _migration_state(connection)
        if state == "partial":
            raise RuntimeError(
                "Partial prescription-foundation migration detected; refusing repair."
            )
        if state == "unmigrated":
            if database_sha256_before != backup_sha256:
                raise RuntimeError("Backup must be byte-identical before migration.")
            if pre_schema != backup_schema:
                raise RuntimeError("Backup and live schema snapshots differ.")
            backup_reference = _value_reference(backup_schema)
            backup_digests = _value_digests(
                backup_connection,
                backup_reference,
            )
            preexisting_digests = _value_digests(connection, backup_reference)
            if backup_digests != preexisting_digests:
                raise RuntimeError("Backup and live value snapshots differ.")
        else:
            if marker[1] != backup_sha256:
                raise RuntimeError("Migration marker does not match this backup.")
            _verify_expected_schema(pre_schema, backup_schema)
            _verify_marker(connection, backup_sha256)
            backup_reference = _value_reference(pre_schema)
            preexisting_digests = _value_digests(connection, backup_reference)

        image_manifest = _image_manifest(connection, database_path)
        before_full_reference = _value_reference(pre_schema)
        before_full_digests = _value_digests(connection, before_full_reference)

        if state == "unmigrated":
            (
                added_prescription_columns,
                added_medicine_columns,
            ) = _apply_migration(
                connection,
                image_manifest,
                backup_sha256,
                failure_injector,
            )
            applied = True

        post_schema = _schema_snapshot(connection)
        _verify_expected_schema(post_schema, backup_schema)
        _verify_marker(connection, backup_sha256)
        _validate_integrity(connection)
        if _ownership_violation_count(connection):
            raise RuntimeError("Relationship verification failed after migration.")

        if _value_digests(connection, before_full_reference) != before_full_digests:
            raise RuntimeError("Pre-existing values changed during migration.")
        if _image_manifest(connection, database_path) != image_manifest:
            raise RuntimeError("Prescription image manifest changed during migration.")
        _verify_image_metadata(connection, image_manifest)

        post_full_reference = _value_reference(post_schema)
        post_full_digests = _value_digests(connection, post_full_reference)
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
        if secondary_sha256 != (
            _sha256_file(secondary_path) if secondary_path.is_file() else None
        ):
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
    if secondary_sha256 != (
        _sha256_file(secondary_path) if secondary_path.is_file() else None
    ):
        raise RuntimeError("Secondary database changed during migration.")

    reopened = _read_only_connection(database_path)
    try:
        _validate_integrity(reopened)
        if _ownership_violation_count(reopened):
            raise RuntimeError("Reopened relationship verification failed.")
        reopened_schema = _schema_snapshot(reopened)
        if reopened_schema != post_schema:
            raise RuntimeError("Committed schema snapshot differs after reopen.")
        _verify_expected_schema(reopened_schema, backup_schema)
        _verify_marker(reopened, backup_sha256)
        if _value_digests(reopened, before_full_reference) != before_full_digests:
            raise RuntimeError("Committed pre-existing value snapshot changed.")
        if _value_digests(reopened, post_full_reference) != post_full_digests:
            raise RuntimeError("Committed full value snapshot differs after reopen.")
        reopened_manifest = _image_manifest(reopened, database_path)
        if reopened_manifest != image_manifest:
            raise RuntimeError("Committed image manifest differs after reopen.")
        _verify_image_metadata(reopened, reopened_manifest)
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
            for table_name, details in preexisting_digests.items()
        },
        "preexisting_value_digests": {
            table_name: details["sha256"]
            for table_name, details in preexisting_digests.items()
        },
        "record_ids_and_values_preserved": True,
        "foreign_key_issues": 0,
        "image_manifest": _manifest_summary(image_manifest),
        "image_metadata_verified": True,
        "added_prescription_columns": added_prescription_columns,
        "added_medicine_columns": added_medicine_columns,
        "created_triggers": (
            list(MEDICINE_PRESCRIPTION_TRIGGER_SQL) if applied else []
        ),
        "backup_unchanged": True,
        "secondary_database_unchanged": True,
    }

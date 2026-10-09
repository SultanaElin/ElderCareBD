import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import models
from database import Base
from security import hash_password, is_password_hash


AUTHORITATIVE_DATABASE_NAME = "eldercare_bd.db"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _table_count(session, model):
    return session.query(model).count()


def migrate_auth_security(database_path, backup_path):
    database_path = Path(database_path).resolve()
    backup_path = Path(backup_path).resolve()

    if database_path.name != AUTHORITATIVE_DATABASE_NAME:
        raise RuntimeError(
            f"Refusing to migrate non-authoritative database: {database_path.name}"
        )
    if not database_path.is_file() or not backup_path.is_file():
        raise RuntimeError("Database and verified backup files are required.")
    if _sha256(database_path) != _sha256(backup_path):
        raise RuntimeError("Backup must be byte-identical before migration.")

    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    session = sessionmaker(bind=engine)()

    try:
        before = {
            "caregivers": _table_count(session, models.Caregiver),
            "patients": _table_count(session, models.Patient),
            "assessments": _table_count(session, models.Assessment),
            "prescriptions": _table_count(session, models.Prescription),
            "medicines": _table_count(session, models.Medicine),
        }
        caregiver_ids = [
            row[0]
            for row in session.query(models.Caregiver.id)
            .order_by(models.Caregiver.id)
            .all()
        ]

        Base.metadata.create_all(bind=engine)

        migrated_passwords = 0
        for caregiver in session.query(models.Caregiver).all():
            if not is_password_hash(caregiver.password):
                caregiver.password = hash_password(caregiver.password)
                migrated_passwords += 1
        session.flush()

        after = {
            "caregivers": _table_count(session, models.Caregiver),
            "patients": _table_count(session, models.Patient),
            "assessments": _table_count(session, models.Assessment),
            "prescriptions": _table_count(session, models.Prescription),
            "medicines": _table_count(session, models.Medicine),
        }
        after_caregiver_ids = [
            row[0]
            for row in session.query(models.Caregiver.id)
            .order_by(models.Caregiver.id)
            .all()
        ]

        if before != after or caregiver_ids != after_caregiver_ids:
            raise RuntimeError("Record counts or caregiver IDs changed during migration.")

        integrity = session.execute(text("PRAGMA integrity_check")).scalar_one()
        foreign_key_issues = session.execute(text("PRAGMA foreign_key_check")).all()
        if integrity != "ok" or foreign_key_issues:
            raise RuntimeError("SQLite integrity verification failed after migration.")

        session.commit()

        return {
            "migrated_passwords": migrated_passwords,
            "record_counts": after,
            "caregiver_ids_preserved": True,
            "integrity": integrity,
            "foreign_key_issues": len(foreign_key_issues),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="Safely add caregiver sessions and hash legacy passwords."
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--backup", required=True)
    args = parser.parse_args()

    result = migrate_auth_security(args.database, args.backup)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

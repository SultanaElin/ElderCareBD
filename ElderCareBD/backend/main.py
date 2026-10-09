from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect

from database import Base, engine
from ml_model_service import warm_ml_models
from otp_delivery import validate_otp_production_configuration
from request_limits import PrescriptionUploadLimitMiddleware
from routers import (
    assessments,
    auth,
    daily_observations,
    medicines,
    patients,
    predictions,
    prescriptions,
)


_TASK15_CAREGIVER_COLUMNS = {
    "identity_normalized": ("VARCHAR(320)", True, None),
    "verification_status": ("VARCHAR(16)", False, "pending"),
    "verified_at": ("DATETIME", True, None),
    "primary_verification_channel": ("VARCHAR(5)", True, None),
}

_TASK15_VERIFICATION_COLUMNS = {
    "id": ("INTEGER", False, None),
    "caregiver_id": ("INTEGER", False, None),
    "channel": ("VARCHAR(5)", False, None),
    "destination_normalized": ("VARCHAR(320)", False, None),
    "otp_digest": ("VARCHAR(64)", False, None),
    "otp_salt": ("VARCHAR(64)", False, None),
    "created_at": ("DATETIME", False, None),
    "expires_at": ("DATETIME", False, None),
    "resend_available_at": ("DATETIME", False, None),
    "resend_window_started_at": ("DATETIME", False, None),
    "failed_attempts": ("INTEGER", False, "0"),
    "max_attempts": ("INTEGER", False, "5"),
    "resend_count": ("INTEGER", False, "0"),
    "delivery_status": ("VARCHAR(16)", False, "sent"),
    "consumed_at": ("DATETIME", True, None),
    "invalidated_at": ("DATETIME", True, None),
}

_TASK15_VERIFICATION_INDEXES = {
    "ix_caregiver_verifications_active_lookup": (
        False,
        (
            "caregiver_id",
            "channel",
            "consumed_at",
            "invalidated_at",
            "created_at",
        ),
    ),
    "ix_caregiver_verifications_expires_at": (False, ("expires_at",)),
    "ux_caregiver_verifications_active_caregiver": (True, ("caregiver_id",)),
}


def _normalized_server_default(value):
    if value is None:
        return None
    normalized = str(value).strip()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {
        "'",
        '"',
    }:
        normalized = normalized[1:-1]
    return normalized.lower()


def _validate_columns(inspector, table_name, expected):
    actual = {column["name"]: column for column in inspector.get_columns(table_name)}
    if set(actual) != set(expected):
        raise RuntimeError(f"The {table_name} Task 15 column contract is incomplete.")
    for column_name, (column_type, nullable, default) in expected.items():
        column = actual[column_name]
        if (
            str(column["type"]).upper() != column_type
            or bool(column["nullable"]) != nullable
            or _normalized_server_default(column.get("default")) != default
        ):
            raise RuntimeError(
                f"The {table_name}.{column_name} Task 15 declaration is invalid."
            )


def _validate_task15_schema(inspector):
    caregiver_columns = {
        column["name"]: column for column in inspector.get_columns("caregivers")
    }
    for column_name, (column_type, nullable, default) in (
        _TASK15_CAREGIVER_COLUMNS.items()
    ):
        column = caregiver_columns.get(column_name)
        if column is None or (
            str(column["type"]).upper() != column_type
            or bool(column["nullable"]) != nullable
            or _normalized_server_default(column.get("default")) != default
        ):
            raise RuntimeError(
                f"The caregivers.{column_name} Task 15 declaration is invalid."
            )

    caregiver_indexes = {
        item["name"]: item for item in inspector.get_indexes("caregivers")
    }
    identity_index = caregiver_indexes.get("ix_caregivers_identity_normalized")
    if identity_index is None or not identity_index.get("unique") or tuple(
        identity_index.get("column_names") or ()
    ) != ("identity_normalized",):
        raise RuntimeError("The normalized caregiver identity constraint is missing.")

    _validate_columns(
        inspector,
        "caregiver_verifications",
        _TASK15_VERIFICATION_COLUMNS,
    )
    verification_indexes = {
        item["name"]: item
        for item in inspector.get_indexes("caregiver_verifications")
    }
    if set(verification_indexes) != set(_TASK15_VERIFICATION_INDEXES):
        raise RuntimeError("The caregiver verification index contract is incomplete.")
    for index_name, (unique, columns) in _TASK15_VERIFICATION_INDEXES.items():
        index = verification_indexes[index_name]
        if bool(index.get("unique")) != unique or tuple(
            index.get("column_names") or ()
        ) != columns:
            raise RuntimeError(f"The {index_name} declaration is invalid.")

    active_index = verification_indexes[
        "ux_caregiver_verifications_active_caregiver"
    ]
    where_clause = str(
        (active_index.get("dialect_options") or {}).get("sqlite_where", "")
    )
    normalized_where = " ".join(where_clause.lower().split())
    if normalized_where != "consumed_at is null and invalidated_at is null":
        raise RuntimeError("The active caregiver verification constraint is invalid.")

    foreign_keys = inspector.get_foreign_keys("caregiver_verifications")
    matching_foreign_keys = [
        foreign_key
        for foreign_key in foreign_keys
        if tuple(foreign_key.get("constrained_columns") or ()) == ("caregiver_id",)
        and foreign_key.get("referred_table") == "caregivers"
        and tuple(foreign_key.get("referred_columns") or ()) == ("id",)
        and str((foreign_key.get("options") or {}).get("ondelete", "")).upper()
        == "CASCADE"
    ]
    if len(matching_foreign_keys) != 1:
        raise RuntimeError("The caregiver verification foreign key is invalid.")


def _initialize_database_schema(database_engine=engine):
    """Create only a fresh schema; refuse to auto-upgrade any existing schema."""

    inspector = inspect(database_engine)
    existing_tables = set(inspector.get_table_names())
    if not existing_tables:
        Base.metadata.create_all(bind=database_engine)
        inspector = inspect(database_engine)
        expected_tables = set(Base.metadata.tables)
        if not expected_tables.issubset(inspector.get_table_names()):
            raise RuntimeError("Fresh database schema creation was incomplete.")
        _validate_task15_schema(inspector)
        return

    expected_tables = set(Base.metadata.tables)
    if not expected_tables.issubset(existing_tables):
        raise RuntimeError(
            "An existing database schema is incomplete; apply the reviewed "
            "database migrations before starting the backend."
        )
    for table_name, table in Base.metadata.tables.items():
        actual_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        if not set(table.columns.keys()).issubset(actual_columns):
            raise RuntimeError(
                "An existing database schema is incomplete; apply the reviewed "
                "database migrations before starting the backend."
            )
    _validate_task15_schema(inspector)


_initialize_database_schema()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_otp_production_configuration()
    warm_ml_models()
    yield


app = FastAPI(
    title="ElderCare BD Backend",
    description="Backend API for ElderCare BD mobile application",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(PrescriptionUploadLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(patients.router)
app.include_router(daily_observations.router)
app.include_router(assessments.router)
app.include_router(medicines.router)
app.include_router(prescriptions.router)
app.include_router(predictions.router)


@app.get("/")
def root():
    return {
        "message": "ElderCare BD backend is running",
        "status": "success"
    }

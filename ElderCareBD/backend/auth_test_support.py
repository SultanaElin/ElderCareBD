"""Test-only helpers for authenticated fixtures outside the auth test suite."""

from datetime import datetime, timezone

import models
from identity import normalize_identity
from security import create_caregiver_session, hash_password


def create_verified_caregiver_session(db, *, name, identity, password):
    """Create an already-verified fixture and return its ID and bearer token.

    Feature tests use this helper so they remain independent of OTP delivery.
    The Task 15 auth tests exercise the real register/verify/login lifecycle.
    """

    normalized = normalize_identity(identity)
    caregiver = models.Caregiver(
        name=name,
        phone_or_email=normalized.value,
        identity_normalized=normalized.value,
        password=hash_password(password),
        verification_status="verified",
        verified_at=datetime.now(timezone.utc).replace(tzinfo=None),
        primary_verification_channel=normalized.channel,
    )
    db.add(caregiver)
    db.flush()
    token = create_caregiver_session(db, caregiver.id)
    db.commit()
    return caregiver.id, token

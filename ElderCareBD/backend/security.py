import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

import models
from database import get_db


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
MAX_ACCEPTED_PASSWORD_ITERATIONS = 2_000_000
PASSWORD_SALT_BYTES = 16
SESSION_TOKEN_BYTES = 32
SESSION_LIFETIME = timedelta(days=30)

_bearer_scheme = HTTPBearer(auto_error=False)


def _utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _encode(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value):
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password):
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "$".join(
        (
            PASSWORD_SCHEME,
            str(PASSWORD_ITERATIONS),
            _encode(salt),
            _encode(derived_key),
        )
    )


def is_password_hash(stored_password):
    return stored_password.startswith(f"{PASSWORD_SCHEME}$")


def verify_password(password, stored_password):
    if not is_password_hash(stored_password):
        return False

    try:
        scheme, raw_iterations, raw_salt, raw_expected = stored_password.split("$")
        iterations = int(raw_iterations)
        salt = _decode(raw_salt)
        expected = _decode(raw_expected)
    except (TypeError, ValueError):
        return False

    if (
        scheme != PASSWORD_SCHEME
        or not 1 <= iterations <= MAX_ACCEPTED_PASSWORD_ITERATIONS
    ):
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return secrets.compare_digest(candidate, expected)


def verify_password_with_legacy_upgrade(caregiver, password):
    stored_password = caregiver.password
    if is_password_hash(stored_password):
        return verify_password(password, stored_password), False

    matches = secrets.compare_digest(stored_password, password)
    if matches:
        caregiver.password = hash_password(password)
    return matches, matches


def _hash_session_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_caregiver_session(db, caregiver_id):
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    db.add(
        models.CaregiverSession(
            caregiver_id=caregiver_id,
            token_hash=_hash_session_token(token),
            created_at=_utc_now(),
            expires_at=_utc_now() + SESSION_LIFETIME,
        )
    )
    return token


def _authentication_error():
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_session(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _authentication_error()

    token_hash = _hash_session_token(credentials.credentials)
    session = db.query(models.CaregiverSession).filter(
        models.CaregiverSession.token_hash == token_hash
    ).first()

    if session is None or session.expires_at <= _utc_now():
        raise _authentication_error()

    return session


def get_current_caregiver(
    session: models.CaregiverSession = Depends(get_current_session),
):
    if (
        session.caregiver is None
        or session.caregiver.verification_status != "verified"
    ):
        raise _authentication_error()
    return session.caregiver

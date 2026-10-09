import math

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import otp_verification
import schemas
from api_serialization import serialize_utc_timestamp
from database import get_db
from identity import (
    EMAIL_CHANNEL,
    IdentityValidationError,
    caregiver_name_key,
    destination_hint,
    normalize_caregiver_name,
    normalize_identity,
)
from otp_delivery import OtpDeliveryError, get_otp_delivery_provider
from otp_verification import (
    OTP_LIFETIME,
    OTP_MAX_ATTEMPTS,
    OTP_MAX_RESENDS_PER_WINDOW,
    OTP_RESEND_COOLDOWN,
    OTP_RESEND_WINDOW,
    OtpSecretConfigurationError,
    get_otp_hmac_secret,
)
from security import (
    SESSION_LIFETIME,
    create_caregiver_session,
    get_current_session,
    hash_password,
    verify_password_with_legacy_upgrade,
)


router = APIRouter(prefix="/auth", tags=["Authentication"])


def _error(status_code, code, message, **details):
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, **details},
    )


def _latest_verification(db, caregiver_id, channel):
    return (
        db.query(models.CaregiverVerification)
        .filter(
            models.CaregiverVerification.caregiver_id == caregiver_id,
            models.CaregiverVerification.channel == channel,
            models.CaregiverVerification.delivery_status == "sent",
            models.CaregiverVerification.consumed_at.is_(None),
            models.CaregiverVerification.invalidated_at.is_(None),
        )
        .order_by(
            models.CaregiverVerification.created_at.desc(),
            models.CaregiverVerification.id.desc(),
        )
        .first()
    )


def _pending_fields(caregiver, verification):
    return {
        "caregiver_id": caregiver.id,
        "verification_required": True,
        "channel": caregiver.primary_verification_channel,
        "destination_hint": destination_hint(
            verification.destination_normalized,
            verification.channel,
        ),
        "expires_at": serialize_utc_timestamp(verification.expires_at),
        "resend_available_at": serialize_utc_timestamp(
            verification.resend_available_at
        ),
    }


def _pending_registration_response(caregiver, verification, message):
    return {"message": message, **_pending_fields(caregiver, verification)}


def _delivery_unavailable(db):
    db.rollback()
    _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "otp_delivery_unavailable",
        "Verification code delivery is temporarily unavailable. Please try again.",
    )


def _configuration_unavailable(db):
    db.rollback()
    _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "otp_service_unavailable",
        "Account verification is temporarily unavailable. Please try again.",
    )


def _new_verification(
    *,
    caregiver_id,
    channel,
    destination,
    material,
    now,
    resend_window_started_at,
    resend_count,
):
    return models.CaregiverVerification(
        caregiver_id=caregiver_id,
        channel=channel,
        destination_normalized=destination,
        otp_digest=material.digest,
        otp_salt=material.salt,
        created_at=now,
        expires_at=now + OTP_LIFETIME,
        resend_available_at=now + OTP_RESEND_COOLDOWN,
        failed_attempts=0,
        max_attempts=OTP_MAX_ATTEMPTS,
        resend_window_started_at=resend_window_started_at,
        resend_count=resend_count,
        delivery_status="sent",
    )


def _find_existing_registration(db, normalized_identity):
    conditions = [
        models.Caregiver.identity_normalized == normalized_identity.value,
        models.Caregiver.phone_or_email == normalized_identity.value,
    ]
    if normalized_identity.channel == EMAIL_CHANNEL:
        conditions.append(
            func.lower(func.trim(models.Caregiver.phone_or_email))
            == normalized_identity.value
        )
    return db.query(models.Caregiver).filter(or_(*conditions)).first()


@router.post(
    "/register-caregiver",
    status_code=status.HTTP_202_ACCEPTED,
)
def register_caregiver(data: schemas.CaregiverCreate, db: Session = Depends(get_db)):
    try:
        normalized_identity = normalize_identity(
            data.phone_or_email,
            requested_channel=data.channel,
        )
        normalized_name = normalize_caregiver_name(data.name)
    except IdentityValidationError as exc:
        _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_identity", str(exc))

    existing = _find_existing_registration(db, normalized_identity)
    if existing is not None:
        if existing.verification_status == "verified":
            _error(
                status.HTTP_409_CONFLICT,
                "caregiver_already_exists",
                "A verified caregiver already uses this phone number or email.",
            )
        if existing.verification_status != "pending":
            _error(
                status.HTTP_409_CONFLICT,
                "caregiver_registration_conflict",
                "This caregiver registration cannot be continued.",
            )
        if caregiver_name_key(existing.name) != caregiver_name_key(normalized_name):
            _error(
                status.HTTP_409_CONFLICT,
                "caregiver_registration_conflict",
                "The pending registration details do not match.",
            )
        verification = _latest_verification(
            db,
            existing.id,
            existing.primary_verification_channel,
        )
        if verification is None:
            _error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "verification_state_unavailable",
                "The pending verification cannot be continued. Please try again later.",
            )
        return _pending_registration_response(
            existing,
            verification,
            "Caregiver registration is awaiting verification.",
        )

    caregiver = models.Caregiver(
        name=normalized_name,
        phone_or_email=normalized_identity.value,
        identity_normalized=normalized_identity.value,
        password=hash_password(data.password),
        verification_status="pending",
        verified_at=None,
        primary_verification_channel=normalized_identity.channel,
    )

    try:
        secret = get_otp_hmac_secret()
    except OtpSecretConfigurationError:
        _configuration_unavailable(db)

    try:
        db.add(caregiver)
        db.flush()
        now = otp_verification.utc_now()
        material = otp_verification.create_otp_material(
            secret,
            caregiver.id,
            normalized_identity.channel,
        )
        verification = _new_verification(
            caregiver_id=caregiver.id,
            channel=normalized_identity.channel,
            destination=normalized_identity.value,
            material=material,
            now=now,
            resend_window_started_at=now,
            resend_count=0,
        )
        db.add(verification)
        db.flush()
        provider = get_otp_delivery_provider()
        provider.send_otp(
            channel=verification.channel,
            destination=verification.destination_normalized,
            code=material.code,
            expires_at=verification.expires_at,
        )
        db.commit()
        db.refresh(caregiver)
        db.refresh(verification)
    except IntegrityError:
        db.rollback()
        _error(
            status.HTTP_409_CONFLICT,
            "caregiver_already_exists",
            "A caregiver already uses this phone number or email.",
        )
    except OtpDeliveryError:
        _delivery_unavailable(db)

    return _pending_registration_response(
        caregiver,
        verification,
        "Verification code sent. Complete verification to activate the account.",
    )


def _find_login_caregiver(db, raw_identity):
    raw_identity = raw_identity.strip()
    try:
        normalized = normalize_identity(raw_identity)
    except IdentityValidationError:
        normalized = None

    caregiver = None
    if normalized is not None:
        caregiver = (
            db.query(models.Caregiver)
            .filter(models.Caregiver.identity_normalized == normalized.value)
            .first()
        )
    if caregiver is None:
        caregiver = (
            db.query(models.Caregiver)
            .filter(
                models.Caregiver.phone_or_email == raw_identity,
                models.Caregiver.verification_status == "verified",
            )
            .first()
        )
    return caregiver


@router.post("/login-caregiver")
def login_caregiver(data: schemas.CaregiverLogin, db: Session = Depends(get_db)):
    caregiver = _find_login_caregiver(db, data.phone_or_email)

    if caregiver is None:
        raise HTTPException(status_code=401, detail="Invalid login credentials")

    password_matches, _ = verify_password_with_legacy_upgrade(
        caregiver,
        data.password,
    )
    if not password_matches:
        raise HTTPException(status_code=401, detail="Invalid login credentials")

    if caregiver.verification_status == "pending":
        verification = _latest_verification(
            db,
            caregiver.id,
            caregiver.primary_verification_channel,
        )
        if verification is None:
            _error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "verification_state_unavailable",
                "The pending verification cannot be continued. Please try again later.",
            )
        _error(
            status.HTTP_403_FORBIDDEN,
            "verification_required",
            "Complete caregiver verification before signing in.",
            **_pending_fields(caregiver, verification),
        )
    if caregiver.verification_status != "verified":
        raise HTTPException(status_code=401, detail="Invalid login credentials")

    access_token = create_caregiver_session(db, caregiver.id)
    db.commit()

    return {
        "message": "Login successful",
        "caregiver_id": caregiver.id,
        "name": caregiver.name,
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": int(SESSION_LIFETIME.total_seconds()),
    }


def _load_pending_caregiver(db, caregiver_id, channel):
    caregiver = db.get(models.Caregiver, caregiver_id)
    if caregiver is None:
        _error(
            status.HTTP_404_NOT_FOUND,
            "verification_not_found",
            "Pending caregiver verification was not found.",
        )
    if caregiver.verification_status == "verified":
        _error(
            status.HTTP_409_CONFLICT,
            "caregiver_already_verified",
            "This caregiver is already verified.",
        )
    if caregiver.verification_status != "pending":
        _error(
            status.HTTP_409_CONFLICT,
            "verification_not_pending",
            "This caregiver cannot be verified.",
        )
    if caregiver.primary_verification_channel != channel:
        _error(
            status.HTTP_400_BAD_REQUEST,
            "verification_channel_mismatch",
            "The verification channel does not match this registration.",
        )
    return caregiver


@router.post("/verify-otp")
def verify_caregiver_otp(
    data: schemas.CaregiverOtpVerification,
    db: Session = Depends(get_db),
):
    caregiver = _load_pending_caregiver(db, data.caregiver_id, data.channel)
    verification = _latest_verification(db, caregiver.id, data.channel)
    if verification is None:
        _error(
            status.HTTP_409_CONFLICT,
            "otp_not_available",
            "No active verification code is available. Request a new code.",
        )

    now = otp_verification.utc_now()
    if verification.expires_at <= now:
        _error(
            status.HTTP_410_GONE,
            "otp_expired",
            "The verification code has expired. Request a new code.",
            resend_available_at=serialize_utc_timestamp(
                verification.resend_available_at
            ),
        )
    if verification.failed_attempts >= verification.max_attempts:
        _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "otp_attempts_exhausted",
            "Too many incorrect verification attempts. Request a new code.",
            attempts_remaining=0,
        )

    try:
        secret = get_otp_hmac_secret()
        matches = otp_verification.verify_otp_code(
            secret,
            caregiver.id,
            verification.channel,
            verification.otp_salt,
            verification.otp_digest,
            data.otp,
        )
    except OtpSecretConfigurationError:
        _configuration_unavailable(db)

    if not matches:
        updated = (
            db.query(models.CaregiverVerification)
            .filter(
                models.CaregiverVerification.id == verification.id,
                models.CaregiverVerification.consumed_at.is_(None),
                models.CaregiverVerification.invalidated_at.is_(None),
                models.CaregiverVerification.expires_at > now,
                models.CaregiverVerification.failed_attempts
                < models.CaregiverVerification.max_attempts,
            )
            .update(
                {
                    models.CaregiverVerification.failed_attempts:
                    models.CaregiverVerification.failed_attempts + 1
                },
                synchronize_session=False,
            )
        )
        if updated != 1:
            db.rollback()
            _error(
                status.HTTP_409_CONFLICT,
                "otp_state_changed",
                "Verification state changed. Please try again.",
            )
        db.commit()
        db.expire_all()
        current = db.get(models.CaregiverVerification, verification.id)
        attempts_remaining = max(
            0,
            current.max_attempts - current.failed_attempts,
        )
        if attempts_remaining == 0:
            _error(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "otp_attempts_exhausted",
                "Too many incorrect verification attempts. Request a new code.",
                attempts_remaining=0,
            )
        _error(
            status.HTTP_400_BAD_REQUEST,
            "invalid_otp",
            "The verification code is incorrect.",
            attempts_remaining=attempts_remaining,
        )

    verification_updated = (
        db.query(models.CaregiverVerification)
        .filter(
            models.CaregiverVerification.id == verification.id,
            models.CaregiverVerification.consumed_at.is_(None),
            models.CaregiverVerification.invalidated_at.is_(None),
            models.CaregiverVerification.expires_at > now,
            models.CaregiverVerification.failed_attempts
            < models.CaregiverVerification.max_attempts,
        )
        .update(
            {models.CaregiverVerification.consumed_at: now},
            synchronize_session=False,
        )
    )
    caregiver_updated = (
        db.query(models.Caregiver)
        .filter(
            models.Caregiver.id == caregiver.id,
            models.Caregiver.verification_status == "pending",
        )
        .update(
            {
                models.Caregiver.verification_status: "verified",
                models.Caregiver.verified_at: now,
            },
            synchronize_session=False,
        )
    )
    if verification_updated != 1 or caregiver_updated != 1:
        db.rollback()
        _error(
            status.HTTP_409_CONFLICT,
            "otp_state_changed",
            "Verification state changed. Please try again.",
        )
    db.commit()

    return {
        "message": "Caregiver verified successfully.",
        "caregiver_id": caregiver.id,
        "verified": True,
        "verification_required": False,
        "verification_status": "verified",
        "verified_at": serialize_utc_timestamp(now),
    }


@router.post("/resend-otp")
def resend_caregiver_otp(
    data: schemas.CaregiverOtpResend,
    db: Session = Depends(get_db),
):
    caregiver = _load_pending_caregiver(db, data.caregiver_id, data.channel)
    old_verification = _latest_verification(db, caregiver.id, data.channel)
    if old_verification is None:
        _error(
            status.HTTP_409_CONFLICT,
            "otp_not_available",
            "No pending verification code can be resent.",
        )

    now = otp_verification.utc_now()
    if old_verification.resend_available_at > now:
        retry_after = max(
            1,
            math.ceil((old_verification.resend_available_at - now).total_seconds()),
        )
        _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "otp_resend_cooldown",
            "Please wait before requesting another verification code.",
            retry_after_seconds=retry_after,
        )

    window_end = old_verification.resend_window_started_at + OTP_RESEND_WINDOW
    if now < window_end and old_verification.resend_count >= OTP_MAX_RESENDS_PER_WINDOW:
        _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "otp_resend_limit",
            "Too many verification codes were requested. Please try again later.",
            retry_after_seconds=max(
                1,
                math.ceil((window_end - now).total_seconds()),
            ),
        )

    if now >= window_end:
        resend_window_started_at = now
        resend_count = 1
    else:
        resend_window_started_at = old_verification.resend_window_started_at
        resend_count = old_verification.resend_count + 1

    try:
        secret = get_otp_hmac_secret()
        material = otp_verification.create_otp_material(
            secret,
            caregiver.id,
            data.channel,
        )
        new_verification = _new_verification(
            caregiver_id=caregiver.id,
            channel=data.channel,
            destination=old_verification.destination_normalized,
            material=material,
            now=now,
            resend_window_started_at=resend_window_started_at,
            resend_count=resend_count,
        )
        provider = get_otp_delivery_provider()
        provider.send_otp(
            channel=new_verification.channel,
            destination=new_verification.destination_normalized,
            code=material.code,
            expires_at=new_verification.expires_at,
        )
    except OtpSecretConfigurationError:
        _configuration_unavailable(db)
    except OtpDeliveryError:
        _delivery_unavailable(db)

    invalidated = (
        db.query(models.CaregiverVerification)
        .filter(
            models.CaregiverVerification.id == old_verification.id,
            models.CaregiverVerification.consumed_at.is_(None),
            models.CaregiverVerification.invalidated_at.is_(None),
            models.CaregiverVerification.resend_available_at <= now,
        )
        .update(
            {models.CaregiverVerification.invalidated_at: now},
            synchronize_session=False,
        )
    )
    if invalidated != 1:
        db.rollback()
        _error(
            status.HTTP_409_CONFLICT,
            "otp_state_changed",
            "Verification state changed. Please try again.",
        )
    db.add(new_verification)
    try:
        db.commit()
        db.refresh(new_verification)
    except IntegrityError:
        db.rollback()
        _error(
            status.HTTP_409_CONFLICT,
            "otp_state_changed",
            "Verification state changed. Please try again.",
        )

    return _pending_registration_response(
        caregiver,
        new_verification,
        "A new verification code was sent.",
    )


@router.post("/logout")
def logout_caregiver(
    session: models.CaregiverSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    db.delete(session)
    db.commit()
    return {"message": "Logout successful"}

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


OTP_DIGITS = 6
OTP_LIFETIME = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN = timedelta(seconds=60)
OTP_MAX_RESENDS_PER_WINDOW = 5
OTP_RESEND_WINDOW = timedelta(hours=1)
OTP_SALT_BYTES = 16


class OtpSecretConfigurationError(RuntimeError):
    """Raised when secure OTP verification cannot be configured."""


@dataclass(frozen=True)
class OtpCodeMaterial:
    code: str
    salt: str
    digest: str


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_otp_hmac_secret():
    secret = os.getenv("ELDERCARE_OTP_HMAC_SECRET", "")
    if len(secret) < 32:
        raise OtpSecretConfigurationError(
            "ELDERCARE_OTP_HMAC_SECRET must contain at least 32 characters."
        )
    return secret


def generate_otp_code():
    return f"{secrets.randbelow(10 ** OTP_DIGITS):0{OTP_DIGITS}d}"


def _digest(secret, caregiver_id, channel, salt, code):
    message = f"{caregiver_id}:{channel}:{salt}:{code}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def create_otp_material(secret, caregiver_id, channel):
    if len(secret) < 32:
        raise OtpSecretConfigurationError("OTP verification secret is too short.")
    code = generate_otp_code()
    salt = secrets.token_hex(OTP_SALT_BYTES)
    return OtpCodeMaterial(
        code=code,
        salt=salt,
        digest=_digest(secret, caregiver_id, channel, salt, code),
    )


def verify_otp_code(secret, caregiver_id, channel, salt, expected_digest, code):
    if len(secret) < 32:
        raise OtpSecretConfigurationError("OTP verification secret is too short.")
    candidate = _digest(secret, caregiver_id, channel, salt, code)
    return hmac.compare_digest(candidate, expected_digest)

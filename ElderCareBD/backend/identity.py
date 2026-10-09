import re
import unicodedata
from dataclasses import dataclass


EMAIL_CHANNEL = "email"
SMS_CHANNEL = "sms"
SUPPORTED_VERIFICATION_CHANNELS = frozenset({EMAIL_CHANNEL, SMS_CHANNEL})

_E164_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")
_EMAIL_LOCAL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$"
)
_EMAIL_DOMAIN_LABEL_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


class IdentityValidationError(ValueError):
    """Raised when a caregiver identity cannot be safely normalized."""


@dataclass(frozen=True)
class NormalizedIdentity:
    value: str
    channel: str


def _normalized_text(value):
    if not isinstance(value, str):
        raise IdentityValidationError("Phone or email must be text.")
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized or len(normalized) > 320:
        raise IdentityValidationError("Enter a valid phone number or email.")
    if any(character.isspace() or ord(character) < 32 for character in normalized):
        raise IdentityValidationError("Enter a valid phone number or email.")
    return normalized


def _normalize_email(value):
    if value.count("@") != 1:
        raise IdentityValidationError("Enter a valid email address.")
    local, domain = value.rsplit("@", 1)
    if (
        not local
        or len(local) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or not _EMAIL_LOCAL_PATTERN.fullmatch(local)
    ):
        raise IdentityValidationError("Enter a valid email address.")

    labels = domain.split(".")
    if (
        len(domain) > 253
        or len(labels) < 2
        or any(not _EMAIL_DOMAIN_LABEL_PATTERN.fullmatch(label) for label in labels)
    ):
        raise IdentityValidationError("Enter a valid email address.")
    return f"{local}@{domain}".lower()


def _normalize_phone(value):
    if not _E164_PATTERN.fullmatch(value):
        raise IdentityValidationError(
            "Enter the phone number in E.164 format, such as +8801XXXXXXXXX."
        )
    return value


def normalize_identity(value, requested_channel=None):
    """Return a strict new-account identity without guessing a country code."""

    normalized = _normalized_text(value)
    if requested_channel is not None and requested_channel not in SUPPORTED_VERIFICATION_CHANNELS:
        raise IdentityValidationError("Unsupported verification channel.")

    inferred_channel = EMAIL_CHANNEL if "@" in normalized else SMS_CHANNEL
    if requested_channel is not None and requested_channel != inferred_channel:
        raise IdentityValidationError(
            "The verification channel does not match the phone or email provided."
        )

    if inferred_channel == EMAIL_CHANNEL:
        canonical = _normalize_email(normalized)
    else:
        canonical = _normalize_phone(normalized)
    return NormalizedIdentity(value=canonical, channel=inferred_channel)


def normalize_caregiver_name(value):
    if not isinstance(value, str):
        raise IdentityValidationError("Caregiver name must be text.")
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if not normalized:
        raise IdentityValidationError("Caregiver name is required.")
    return normalized


def caregiver_name_key(value):
    return normalize_caregiver_name(value).casefold()


def destination_hint(destination, channel):
    if channel == EMAIL_CHANNEL:
        local, domain = destination.rsplit("@", 1)
        visible = local[:1]
        return f"{visible}***@{domain}"
    if channel == SMS_CHANNEL:
        visible_prefix_length = min(4, max(1, len(destination) - 4))
        visible_prefix = destination[:visible_prefix_length]
        visible_suffix = destination[-4:]
        hidden_count = max(
            4,
            len(destination) - visible_prefix_length - len(visible_suffix),
        )
        return f"{visible_prefix}{'*' * hidden_count}{visible_suffix}"
    raise IdentityValidationError("Unsupported verification channel.")

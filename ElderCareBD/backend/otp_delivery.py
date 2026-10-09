import os
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from functools import lru_cache

from identity import EMAIL_CHANNEL, SMS_CHANNEL
from otp_verification import get_otp_hmac_secret


class OtpDeliveryError(RuntimeError):
    """A sanitized OTP delivery failure suitable for route-level handling."""


class OtpDeliveryConfigurationError(OtpDeliveryError):
    """Raised when the selected delivery provider is not safely configured."""


class OtpDeliveryProvider:
    def send_otp(self, *, channel, destination, code, expires_at):
        raise NotImplementedError


@dataclass(frozen=True)
class CapturedOtpDelivery:
    channel: str
    destination: str
    code: str
    expires_at: datetime


class CaptureOtpDeliveryProvider(OtpDeliveryProvider):
    """Explicit test/development provider; it is never selected in production."""

    def __init__(self):
        self.deliveries = []

    def send_otp(self, *, channel, destination, code, expires_at):
        self.deliveries.append(
            CapturedOtpDelivery(
                channel=channel,
                destination=destination,
                code=code,
                expires_at=expires_at,
            )
        )


class DisabledOtpDeliveryProvider(OtpDeliveryProvider):
    def __init__(self, channel):
        self.channel = channel

    def send_otp(self, *, channel, destination, code, expires_at):
        del destination, code, expires_at
        if channel != self.channel:
            raise OtpDeliveryConfigurationError(
                "The OTP delivery channel is not configured."
            )
        raise OtpDeliveryConfigurationError(
            "The OTP delivery channel is not configured."
        )


class SmtpOtpDeliveryProvider(OtpDeliveryProvider):
    def __init__(
        self,
        *,
        host,
        port,
        sender,
        username=None,
        password=None,
        starttls=True,
        use_ssl=False,
        timeout_seconds=10,
    ):
        if not host or not sender:
            raise OtpDeliveryConfigurationError(
                "Email OTP delivery is not configured."
            )
        if bool(username) != bool(password):
            raise OtpDeliveryConfigurationError(
                "SMTP username and password must be configured together."
            )
        if starttls and use_ssl:
            raise OtpDeliveryConfigurationError(
                "SMTP STARTTLS and SSL modes cannot both be enabled."
            )
        self.host = host
        self.port = port
        self.sender = sender
        self.username = username
        self.password = password
        self.starttls = starttls
        self.use_ssl = use_ssl
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls):
        return cls(
            host=os.getenv("ELDERCARE_SMTP_HOST", "").strip(),
            port=_integer_setting("ELDERCARE_SMTP_PORT", 587, minimum=1, maximum=65535),
            sender=os.getenv("ELDERCARE_SMTP_FROM", "").strip(),
            username=os.getenv("ELDERCARE_SMTP_USERNAME") or None,
            password=os.getenv("ELDERCARE_SMTP_PASSWORD") or None,
            starttls=_boolean_setting("ELDERCARE_SMTP_STARTTLS", True),
            use_ssl=_boolean_setting("ELDERCARE_SMTP_SSL", False),
            timeout_seconds=_integer_setting(
                "ELDERCARE_SMTP_TIMEOUT_SECONDS", 10, minimum=1, maximum=60
            ),
        )

    def send_otp(self, *, channel, destination, code, expires_at):
        if channel != EMAIL_CHANNEL:
            raise OtpDeliveryConfigurationError(
                "Email provider cannot deliver an SMS OTP."
            )
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = destination
        message["Subject"] = "Your ElderCareBD verification code"
        message.set_content(
            "Your ElderCareBD verification code is "
            f"{code}. It expires in 10 minutes. Do not share this code with "
            "anyone. If you did not request it, you can ignore this message."
        )
        smtp_class = smtplib.SMTP_SSL if self.use_ssl else smtplib.SMTP
        try:
            with smtp_class(
                self.host,
                self.port,
                timeout=self.timeout_seconds,
            ) as client:
                if self.starttls:
                    client.starttls()
                if self.username is not None:
                    client.login(self.username, self.password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise OtpDeliveryError("OTP delivery failed.") from exc


class ChannelOtpDeliveryProvider(OtpDeliveryProvider):
    def __init__(self, *, email_provider, sms_provider):
        self.email_provider = email_provider
        self.sms_provider = sms_provider

    def send_otp(self, *, channel, destination, code, expires_at):
        if channel == EMAIL_CHANNEL:
            provider = self.email_provider
        elif channel == SMS_CHANNEL:
            provider = self.sms_provider
        else:
            raise OtpDeliveryConfigurationError(
                "The OTP delivery channel is not supported."
            )
        provider.send_otp(
            channel=channel,
            destination=destination,
            code=code,
            expires_at=expires_at,
        )


def _boolean_setting(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise OtpDeliveryConfigurationError(f"{name} must be a boolean value.")


def _integer_setting(name, default, *, minimum, maximum):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise OtpDeliveryConfigurationError(
            f"{name} must be an integer."
        ) from exc
    if value < minimum or value > maximum:
        raise OtpDeliveryConfigurationError(
            f"{name} is outside the supported range."
        )
    return value


@lru_cache(maxsize=1)
def get_otp_delivery_provider():
    mode = os.getenv("ELDERCARE_OTP_DELIVERY_MODE", "smtp").strip().lower()
    environment = os.getenv("ELDERCARE_ENVIRONMENT", "production").strip().lower()
    if mode == "capture":
        if environment not in {"development", "dev", "test", "testing", "local"}:
            raise OtpDeliveryConfigurationError(
                "Capture OTP delivery is forbidden in production."
            )
        return CaptureOtpDeliveryProvider()
    if mode == "smtp":
        return ChannelOtpDeliveryProvider(
            email_provider=SmtpOtpDeliveryProvider.from_environment(),
            sms_provider=DisabledOtpDeliveryProvider(SMS_CHANNEL),
        )
    if mode == "disabled":
        return ChannelOtpDeliveryProvider(
            email_provider=DisabledOtpDeliveryProvider(EMAIL_CHANNEL),
            sms_provider=DisabledOtpDeliveryProvider(SMS_CHANNEL),
        )
    raise OtpDeliveryConfigurationError("Unsupported OTP delivery mode.")


def validate_otp_production_configuration():
    """Fail closed when the application starts in a production environment."""

    environment = os.getenv("ELDERCARE_ENVIRONMENT", "production").strip().lower()
    mode = os.getenv("ELDERCARE_OTP_DELIVERY_MODE", "smtp").strip().lower()
    get_otp_hmac_secret()
    if environment in {"production", "prod"} and mode in {"capture", "disabled"}:
        raise OtpDeliveryConfigurationError(
            "A disabled or capture-only OTP provider is forbidden in production."
        )
    get_otp_delivery_provider()

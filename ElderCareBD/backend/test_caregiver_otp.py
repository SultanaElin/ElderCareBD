import hashlib
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import otp_delivery
import otp_verification
from database import Base, get_db
from identity import destination_hint
from otp_delivery import (
    CaptureOtpDeliveryProvider,
    OtpDeliveryConfigurationError,
    OtpDeliveryError,
)
from routers import auth, patients
from security import create_caregiver_session
from test_core_workflow import FastApiRequestHarness, _database_signatures


TEST_OTP_SECRET = "task15-test-only-hmac-secret-32-characters-minimum"


class _FailingDeliveryProvider:
    def send_otp(self, **_kwargs):
        raise OtpDeliveryError("private provider failure")


class CaregiverOtpTest(unittest.TestCase):
    def setUp(self):
        self.database_signatures = _database_signatures()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session = sessionmaker(bind=self.engine)()

        app = FastAPI()
        app.include_router(auth.router)
        app.include_router(patients.router)

        def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = FastApiRequestHarness(app)
        self.provider = CaptureOtpDeliveryProvider()
        self.now = datetime(2026, 9, 12, 6, 0, 0)
        self.delivery_patch = patch.object(
            auth,
            "get_otp_delivery_provider",
            return_value=self.provider,
        )
        self.secret_patch = patch.object(
            auth,
            "get_otp_hmac_secret",
            return_value=TEST_OTP_SECRET,
        )
        self.clock_patch = patch.object(
            auth.otp_verification,
            "utc_now",
            side_effect=lambda: self.now,
        )
        self.delivery_patch.start()
        self.secret_patch.start()
        self.clock_patch.start()

    def tearDown(self):
        self.clock_patch.stop()
        self.secret_patch.stop()
        self.delivery_patch.stop()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.assertEqual(self.database_signatures, _database_signatures())

    def _register(
        self,
        *,
        name="Caregiver One",
        identity="caregiver@example.invalid",
        password="test-password",
        channel=None,
    ):
        payload = {
            "name": name,
            "phone_or_email": identity,
            "password": password,
        }
        if channel is not None:
            payload["channel"] = channel
        return self.client.request("POST", "/auth/register-caregiver", payload)

    def _verify(self, caregiver_id, otp, channel="email"):
        return self.client.request(
            "POST",
            "/auth/verify-otp",
            {"caregiver_id": caregiver_id, "channel": channel, "otp": otp},
        )

    def test_registration_is_pending_normalized_and_contains_no_secret(self):
        status_code, body = self._register(
            identity="  CareGiver@Example.Invalid  ",
            channel="email",
        )

        self.assertEqual(status_code, 202)
        self.assertEqual(
            set(body),
            {
                "message",
                "caregiver_id",
                "verification_required",
                "channel",
                "destination_hint",
                "expires_at",
                "resend_available_at",
            },
        )
        self.assertTrue(body["verification_required"])
        self.assertEqual(body["channel"], "email")
        self.assertTrue(body["expires_at"].endswith("Z"))
        self.assertTrue(body["resend_available_at"].endswith("Z"))
        self.assertNotIn("access_token", body)
        self.assertNotIn("otp", body)

        caregiver = self.session.get(models.Caregiver, body["caregiver_id"])
        verification = self.session.query(models.CaregiverVerification).one()
        delivered = self.provider.deliveries[0]
        self.assertEqual(caregiver.phone_or_email, "caregiver@example.invalid")
        self.assertEqual(caregiver.identity_normalized, caregiver.phone_or_email)
        self.assertEqual(caregiver.verification_status, "pending")
        self.assertIsNone(caregiver.verified_at)
        self.assertEqual(verification.destination_normalized, caregiver.phone_or_email)
        self.assertEqual(verification.delivery_status, "sent")
        self.assertEqual(verification.max_attempts, 5)
        self.assertRegex(delivered.code, r"^[0-9]{6}$")
        self.assertNotEqual(verification.otp_digest, delivered.code)
        self.assertNotEqual(verification.otp_salt, delivered.code)
        self.assertEqual(len(verification.otp_digest), 64)

    def test_pending_duplicate_is_idempotent_but_conflicting_name_is_rejected(self):
        status_code, first = self._register(
            name="Caregiver   One",
            identity="Caregiver@Example.Invalid",
        )
        self.assertEqual(status_code, 202)

        status_code, repeated = self._register(
            name=" caregiver one ",
            identity="caregiver@example.invalid",
        )
        self.assertEqual(status_code, 202)
        self.assertEqual(repeated["caregiver_id"], first["caregiver_id"])
        self.assertEqual(len(self.provider.deliveries), 1)
        self.assertEqual(self.session.query(models.Caregiver).count(), 1)
        self.assertEqual(self.session.query(models.CaregiverVerification).count(), 1)

        status_code, body = self._register(
            name="Different Caregiver",
            identity="caregiver@example.invalid",
        )
        self.assertEqual(status_code, 409)
        self.assertEqual(body["detail"]["code"], "caregiver_registration_conflict")

    def test_initial_provider_failure_rolls_back_everything(self):
        with patch.object(
            auth,
            "get_otp_delivery_provider",
            return_value=_FailingDeliveryProvider(),
        ):
            status_code, body = self._register()

        self.assertEqual(status_code, 503)
        self.assertEqual(body["detail"]["code"], "otp_delivery_unavailable")
        self.assertNotIn("private", str(body).lower())
        self.assertEqual(self.session.query(models.Caregiver).count(), 0)
        self.assertEqual(self.session.query(models.CaregiverVerification).count(), 0)

    def test_pending_login_is_structured_and_verification_then_login_succeeds(self):
        status_code, registration = self._register()
        self.assertEqual(status_code, 202)
        caregiver_id = registration["caregiver_id"]
        otp = self.provider.deliveries[-1].code

        status_code, wrong_login = self.client.request(
            "POST",
            "/auth/login-caregiver",
            {
                "phone_or_email": "CAREGIVER@EXAMPLE.INVALID",
                "password": "wrong-password",
            },
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(wrong_login["detail"], "Invalid login credentials")

        status_code, pending_login = self.client.request(
            "POST",
            "/auth/login-caregiver",
            {
                "phone_or_email": "CAREGIVER@EXAMPLE.INVALID",
                "password": "test-password",
            },
        )
        self.assertEqual(status_code, 403)
        detail = pending_login["detail"]
        self.assertEqual(detail["code"], "verification_required")
        self.assertEqual(detail["caregiver_id"], caregiver_id)
        self.assertTrue(detail["expires_at"].endswith("Z"))
        self.assertTrue(detail["resend_available_at"].endswith("Z"))
        self.assertNotIn("access_token", detail)

        status_code, verified = self._verify(caregiver_id, otp)
        self.assertEqual(status_code, 200)
        self.assertEqual(verified["verification_status"], "verified")
        self.assertIs(verified["verified"], True)
        self.assertIs(verified["verification_required"], False)
        self.assertTrue(verified["verified_at"].endswith("Z"))
        self.assertNotIn("access_token", verified)

        status_code, login = self.client.request(
            "POST",
            "/auth/login-caregiver",
            {
                "phone_or_email": "caregiver@example.invalid",
                "password": "test-password",
            },
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(login["access_token"])
        self.assertEqual(login["caregiver_id"], caregiver_id)

        status_code, replay = self._verify(caregiver_id, otp)
        self.assertEqual(status_code, 409)
        self.assertEqual(replay["detail"]["code"], "caregiver_already_verified")

    def test_wrong_codes_are_atomically_limited_to_five_attempts(self):
        _, registration = self._register()
        caregiver_id = registration["caregiver_id"]
        real_otp = self.provider.deliveries[-1].code
        wrong_otp = "000000" if real_otp != "000000" else "000001"

        for expected_remaining in (4, 3, 2, 1):
            status_code, body = self._verify(caregiver_id, wrong_otp)
            self.assertEqual(status_code, 400)
            self.assertEqual(body["detail"]["code"], "invalid_otp")
            self.assertEqual(
                body["detail"]["attempts_remaining"],
                expected_remaining,
            )

        status_code, body = self._verify(caregiver_id, wrong_otp)
        self.assertEqual(status_code, 429)
        self.assertEqual(body["detail"]["code"], "otp_attempts_exhausted")
        self.assertEqual(body["detail"]["attempts_remaining"], 0)

        status_code, body = self._verify(caregiver_id, real_otp)
        self.assertEqual(status_code, 429)
        self.assertEqual(body["detail"]["code"], "otp_attempts_exhausted")

    def test_code_expiring_exactly_now_is_rejected(self):
        _, registration = self._register()
        verification = self.session.query(models.CaregiverVerification).one()
        self.now = verification.expires_at

        status_code, body = self._verify(
            registration["caregiver_id"],
            self.provider.deliveries[-1].code,
        )
        self.assertEqual(status_code, 410)
        self.assertEqual(body["detail"]["code"], "otp_expired")

    def test_resend_cooldown_rotation_limit_and_provider_rollback(self):
        _, registration = self._register()
        caregiver_id = registration["caregiver_id"]
        old_verification = self.session.query(models.CaregiverVerification).one()

        status_code, body = self.client.request(
            "POST",
            "/auth/resend-otp",
            {"caregiver_id": caregiver_id, "channel": "email"},
        )
        self.assertEqual(status_code, 429)
        self.assertEqual(body["detail"]["code"], "otp_resend_cooldown")
        self.assertEqual(body["detail"]["retry_after_seconds"], 60)

        self.now += timedelta(seconds=60)
        with patch.object(
            auth,
            "get_otp_delivery_provider",
            return_value=_FailingDeliveryProvider(),
        ):
            status_code, body = self.client.request(
                "POST",
                "/auth/resend-otp",
                {"caregiver_id": caregiver_id, "channel": "email"},
            )
        self.assertEqual(status_code, 503)
        self.assertEqual(body["detail"]["code"], "otp_delivery_unavailable")
        self.session.refresh(old_verification)
        self.assertIsNone(old_verification.invalidated_at)
        self.assertEqual(self.session.query(models.CaregiverVerification).count(), 1)

        status_code, resent = self.client.request(
            "POST",
            "/auth/resend-otp",
            {"caregiver_id": caregiver_id, "channel": "email"},
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(resent["expires_at"].endswith("Z"))
        self.session.refresh(old_verification)
        self.assertEqual(old_verification.invalidated_at, self.now)
        new_verification = self.session.query(models.CaregiverVerification).filter(
            models.CaregiverVerification.invalidated_at.is_(None)
        ).one()
        self.assertEqual(new_verification.resend_count, 1)

        new_verification.resend_available_at = self.now
        new_verification.resend_count = 5
        self.session.commit()
        status_code, body = self.client.request(
            "POST",
            "/auth/resend-otp",
            {"caregiver_id": caregiver_id, "channel": "email"},
        )
        self.assertEqual(status_code, 429)
        self.assertEqual(body["detail"]["code"], "otp_resend_limit")

    def test_phone_requires_e164_and_channel_must_match(self):
        status_code, _ = self._register(identity="01712345678", channel="sms")
        self.assertEqual(status_code, 422)

        status_code, _ = self._register(
            identity="+8801712345678",
            channel="email",
        )
        self.assertEqual(status_code, 422)

        status_code, body = self._register(
            identity="+8801712345678",
            channel="sms",
        )
        self.assertEqual(status_code, 202)
        self.assertEqual(body["channel"], "sms")
        self.assertEqual(self.provider.deliveries[-1].destination, "+8801712345678")

        caregiver_id = body["caregiver_id"]
        otp = self.provider.deliveries[-1].code
        wrong_otp = "000000" if otp != "000000" else "000001"
        status_code, wrong = self._verify(caregiver_id, wrong_otp, channel="sms")
        self.assertEqual(status_code, 400)
        self.assertEqual(wrong["detail"]["code"], "invalid_otp")

        status_code, verified = self._verify(caregiver_id, otp, channel="sms")
        self.assertEqual(status_code, 200)
        self.assertIs(verified["verified"], True)

        status_code, login = self.client.request(
            "POST",
            "/auth/login-caregiver",
            {
                "phone_or_email": "+8801712345678",
                "password": "test-password",
            },
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(login["access_token"])

    def test_generation_supports_leading_zero_and_is_not_deterministic(self):
        with patch.object(otp_verification.secrets, "randbelow", return_value=17):
            self.assertEqual(otp_verification.generate_otp_code(), "000017")

        generated = {otp_verification.generate_otp_code() for _ in range(32)}
        self.assertGreater(len(generated), 1)
        self.assertTrue(all(len(code) == 6 and code.isdigit() for code in generated))

    def test_wrong_then_correct_code_succeeds_and_channel_mismatch_is_safe(self):
        _, registration = self._register()
        caregiver_id = registration["caregiver_id"]
        real_otp = self.provider.deliveries[-1].code
        wrong_otp = "000000" if real_otp != "000000" else "000001"

        status_code, wrong = self._verify(caregiver_id, wrong_otp)
        self.assertEqual(status_code, 400)
        self.assertEqual(wrong["detail"]["attempts_remaining"], 4)

        status_code, mismatch = self._verify(caregiver_id, real_otp, channel="sms")
        self.assertEqual(status_code, 400)
        self.assertEqual(
            mismatch["detail"]["code"],
            "verification_channel_mismatch",
        )

        status_code, verified = self._verify(caregiver_id, real_otp)
        self.assertEqual(status_code, 200)
        self.assertIs(verified["verified"], True)

    def test_resend_invalidates_old_code_and_new_code_is_single_use(self):
        _, registration = self._register()
        caregiver_id = registration["caregiver_id"]
        old_code = self.provider.deliveries[-1].code
        expected_new_code = "999999" if old_code != "999999" else "888888"
        self.now += timedelta(seconds=60)

        with patch.object(
            auth.otp_verification,
            "generate_otp_code",
            return_value=expected_new_code,
        ):
            status_code, _ = self.client.request(
                "POST",
                "/auth/resend-otp",
                {"caregiver_id": caregiver_id, "channel": "email"},
            )
        self.assertEqual(status_code, 200)
        new_code = self.provider.deliveries[-1].code
        self.assertEqual(new_code, expected_new_code)

        status_code, old_result = self._verify(caregiver_id, old_code)
        self.assertEqual(status_code, 400)
        self.assertEqual(old_result["detail"]["code"], "invalid_otp")

        status_code, verified = self._verify(caregiver_id, new_code)
        self.assertEqual(status_code, 200)
        self.assertNotIn("access_token", verified)
        status_code, replay = self._verify(caregiver_id, new_code)
        self.assertEqual(status_code, 409)
        self.assertEqual(replay["detail"]["code"], "caregiver_already_verified")

    def test_verified_duplicate_and_malformed_email_are_rejected(self):
        status_code, malformed = self._register(
            identity="not-an-email",
            channel="email",
        )
        self.assertEqual(status_code, 422)
        self.assertEqual(malformed["detail"]["code"], "invalid_identity")

        _, registration = self._register()
        status_code, _ = self._verify(
            registration["caregiver_id"],
            self.provider.deliveries[-1].code,
        )
        self.assertEqual(status_code, 200)
        status_code, duplicate = self._register()
        self.assertEqual(status_code, 409)
        self.assertEqual(duplicate["detail"]["code"], "caregiver_already_exists")

    def test_destination_masking_never_returns_full_destination(self):
        self.assertEqual(
            destination_hint("caregiver@example.invalid", "email"),
            "c***@example.invalid",
        )
        self.assertEqual(
            destination_hint("+8801712345678", "sms"),
            "+880******5678",
        )

    def test_pending_caregiver_session_is_rejected_defensively(self):
        _, registration = self._register()
        token = create_caregiver_session(self.session, registration["caregiver_id"])
        self.session.commit()

        status_code, body = self.client.request(
            "GET",
            "/patients/",
            token=token,
        )
        self.assertEqual(status_code, 401)
        self.assertEqual(body["detail"], "Authentication required.")
        stored = self.session.query(models.CaregiverSession).one()
        self.assertEqual(
            stored.token_hash,
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
        )


class OtpProviderConfigurationTest(unittest.TestCase):
    def tearDown(self):
        otp_delivery.get_otp_delivery_provider.cache_clear()

    def test_unsafe_production_modes_fail_closed(self):
        for mode in ("capture", "disabled"):
            with self.subTest(mode=mode), patch.dict(
                os.environ,
                {
                    "ELDERCARE_ENVIRONMENT": "production",
                    "ELDERCARE_OTP_DELIVERY_MODE": mode,
                    "ELDERCARE_OTP_HMAC_SECRET": TEST_OTP_SECRET,
                },
                clear=True,
            ):
                otp_delivery.get_otp_delivery_provider.cache_clear()
                with self.assertRaises(OtpDeliveryConfigurationError):
                    otp_delivery.validate_otp_production_configuration()

    def test_production_smtp_requires_configuration(self):
        with patch.dict(
            os.environ,
            {
                "ELDERCARE_ENVIRONMENT": "production",
                "ELDERCARE_OTP_DELIVERY_MODE": "smtp",
                "ELDERCARE_OTP_HMAC_SECRET": TEST_OTP_SECRET,
            },
            clear=True,
        ):
            otp_delivery.get_otp_delivery_provider.cache_clear()
            with self.assertRaises(OtpDeliveryConfigurationError):
                otp_delivery.validate_otp_production_configuration()

    def test_complete_production_gmail_smtp_configuration_is_accepted(self):
        with patch.dict(
            os.environ,
            {
                "ELDERCARE_ENVIRONMENT": "production",
                "ELDERCARE_OTP_DELIVERY_MODE": "smtp",
                "ELDERCARE_OTP_HMAC_SECRET": TEST_OTP_SECRET,
                "ELDERCARE_SMTP_HOST": "smtp.gmail.com",
                "ELDERCARE_SMTP_PORT": "587",
                "ELDERCARE_SMTP_FROM": "otp-sender@example.invalid",
                "ELDERCARE_SMTP_USERNAME": "otp-sender@example.invalid",
                "ELDERCARE_SMTP_PASSWORD": "test-only-app-password",
                "ELDERCARE_SMTP_STARTTLS": "true",
                "ELDERCARE_SMTP_SSL": "false",
            },
            clear=True,
        ):
            otp_delivery.get_otp_delivery_provider.cache_clear()
            otp_delivery.validate_otp_production_configuration()
            provider = otp_delivery.get_otp_delivery_provider()
            self.assertIsInstance(provider, otp_delivery.ChannelOtpDeliveryProvider)
            self.assertIsInstance(
                provider.email_provider,
                otp_delivery.SmtpOtpDeliveryProvider,
            )
            self.assertEqual(provider.email_provider.host, "smtp.gmail.com")
            self.assertEqual(provider.email_provider.port, 587)
            self.assertTrue(provider.email_provider.starttls)
            self.assertFalse(provider.email_provider.use_ssl)

    def test_explicit_test_capture_configuration_is_accepted(self):
        with patch.dict(
            os.environ,
            {
                "ELDERCARE_ENVIRONMENT": "test",
                "ELDERCARE_OTP_DELIVERY_MODE": "capture",
                "ELDERCARE_OTP_HMAC_SECRET": TEST_OTP_SECRET,
            },
            clear=True,
        ):
            otp_delivery.get_otp_delivery_provider.cache_clear()
            otp_delivery.validate_otp_production_configuration()
            self.assertIsInstance(
                otp_delivery.get_otp_delivery_provider(),
                CaptureOtpDeliveryProvider,
            )


if __name__ == "__main__":
    unittest.main()

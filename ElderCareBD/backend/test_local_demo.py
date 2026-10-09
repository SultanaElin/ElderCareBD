import os
import unittest
from unittest.mock import patch

from otp_delivery import CaptureOtpDeliveryProvider
from run_local_demo import (
    configure_local_capture_environment,
    latest_captured_otp,
)


class LocalDemoConfigurationTest(unittest.TestCase):
    def test_explicit_local_capture_generates_ephemeral_secret(self):
        environment = {}

        generated = configure_local_capture_environment(environment)

        self.assertTrue(generated)
        self.assertEqual(environment["ELDERCARE_ENVIRONMENT"], "development")
        self.assertEqual(environment["ELDERCARE_OTP_DELIVERY_MODE"], "capture")
        self.assertGreaterEqual(len(environment["ELDERCARE_OTP_HMAC_SECRET"]), 32)

    def test_existing_valid_secret_is_preserved(self):
        secret = "x" * 32
        environment = {
            "ELDERCARE_ENVIRONMENT": "local",
            "ELDERCARE_OTP_DELIVERY_MODE": "capture",
            "ELDERCARE_OTP_HMAC_SECRET": secret,
        }

        generated = configure_local_capture_environment(environment)

        self.assertFalse(generated)
        self.assertEqual(environment["ELDERCARE_OTP_HMAC_SECRET"], secret)

    def test_production_and_non_capture_modes_are_refused(self):
        with self.assertRaisesRegex(RuntimeError, "forbidden in production"):
            configure_local_capture_environment(
                {"ELDERCARE_ENVIRONMENT": "production"}
            )
        with self.assertRaisesRegex(RuntimeError, "must be unset"):
            configure_local_capture_environment(
                {
                    "ELDERCARE_ENVIRONMENT": "development",
                    "ELDERCARE_OTP_DELIVERY_MODE": "smtp",
                }
            )

    def test_latest_otp_is_available_only_from_capture_provider(self):
        provider = CaptureOtpDeliveryProvider()
        self.assertIsNone(latest_captured_otp(provider))
        provider.send_otp(
            channel="email",
            destination="synthetic@example.invalid",
            code="012345",
            expires_at=None,
        )
        self.assertEqual(latest_captured_otp(provider), "012345")

    def test_configuration_does_not_mutate_process_environment_when_mapping_given(self):
        with patch.dict(os.environ, {}, clear=True):
            configure_local_capture_environment({})
            self.assertNotIn("ELDERCARE_ENVIRONMENT", os.environ)
            self.assertNotIn("ELDERCARE_OTP_DELIVERY_MODE", os.environ)
            self.assertNotIn("ELDERCARE_OTP_HMAC_SECRET", os.environ)


if __name__ == "__main__":
    unittest.main()

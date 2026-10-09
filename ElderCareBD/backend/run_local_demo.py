"""Run the backend with an explicit, terminal-only local OTP capture console."""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import threading
import time
from collections.abc import MutableMapping
from pathlib import Path


_LOCAL_ENVIRONMENTS = {"development", "dev", "local", "test", "testing"}
_PRODUCTION_ENVIRONMENTS = {"production", "prod"}
_BACKEND_DIR = Path(__file__).resolve().parent


def configure_local_capture_environment(
    environment: MutableMapping[str, str] | None = None,
) -> bool:
    """Configure explicit process-local capture mode.

    Returns ``True`` when a fresh ephemeral HMAC secret was generated. The
    function refuses to override production or a different delivery provider.
    """

    environment = os.environ if environment is None else environment
    selected_environment = environment.get("ELDERCARE_ENVIRONMENT", "").strip().lower()
    selected_mode = environment.get("ELDERCARE_OTP_DELIVERY_MODE", "").strip().lower()

    if selected_environment in _PRODUCTION_ENVIRONMENTS:
        raise RuntimeError("Local OTP capture is forbidden in production.")
    if selected_environment and selected_environment not in _LOCAL_ENVIRONMENTS:
        raise RuntimeError("ELDERCARE_ENVIRONMENT is not a supported local value.")
    if selected_mode and selected_mode != "capture":
        raise RuntimeError(
            "ELDERCARE_OTP_DELIVERY_MODE must be unset or explicitly set to capture."
        )

    environment["ELDERCARE_ENVIRONMENT"] = selected_environment or "development"
    environment["ELDERCARE_OTP_DELIVERY_MODE"] = "capture"

    secret = environment.get("ELDERCARE_OTP_HMAC_SECRET", "")
    if len(secret) >= 32:
        return False
    environment["ELDERCARE_OTP_HMAC_SECRET"] = secrets.token_urlsafe(32)
    return True


def latest_captured_otp(provider) -> str | None:
    """Return only the newest in-memory development OTP, if one exists."""

    from otp_delivery import CaptureOtpDeliveryProvider

    if not isinstance(provider, CaptureOtpDeliveryProvider):
        raise RuntimeError("The active OTP provider is not the local capture provider.")
    if not provider.deliveries:
        return None
    return provider.deliveries[-1].code


def _wait_for_server(server, server_thread, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while server_thread.is_alive() and not server.started:
        if time.monotonic() >= deadline:
            server.should_exit = True
            raise RuntimeError("Backend startup timed out.")
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("Backend startup failed; review the server output above.")


def _run_console(server, server_thread) -> None:
    from otp_delivery import get_otp_delivery_provider

    provider = get_otp_delivery_provider()
    print(
        "\nLocal demo OTP console ready. Commands: otp, status, quit.\n"
        "The OTP is never exposed by an HTTP endpoint or API response."
    )
    while server_thread.is_alive():
        try:
            command = input("eldercare-demo> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            command = "quit"

        if command == "otp":
            code = latest_captured_otp(provider)
            if code is None:
                print("No OTP has been captured in this process yet.")
            else:
                print(f"Latest local-demo OTP: {code}")
        elif command == "status":
            print(
                "Backend running; "
                f"captured OTP deliveries in memory: {len(provider.deliveries)}"
            )
        elif command in {"quit", "exit"}:
            server.should_exit = True
            break
        elif command:
            print("Unknown command. Use: otp, status, quit.")


def _parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Run ElderCareBD for an explicit local/physical-device demo."
    )
    parser.add_argument(
        "--capture-otp",
        action="store_true",
        help="explicitly enable the in-memory, terminal-only local OTP provider",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if not args.capture_otp:
        parser.error("--capture-otp is required; local OTP capture is never implicit")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    generated_secret = configure_local_capture_environment()
    os.chdir(_BACKEND_DIR)
    if str(_BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(_BACKEND_DIR))

    import uvicorn

    config = uvicorn.Config("main:app", host=args.host, port=args.port)
    server = uvicorn.Server(config)
    server_thread = threading.Thread(
        target=server.run,
        name="eldercare-local-demo-server",
        daemon=True,
    )

    if generated_secret:
        print(
            "Generated an ephemeral OTP HMAC secret for this process. "
            "Restarting invalidates outstanding local-demo OTPs."
        )
    print("LOCAL DEVELOPMENT ONLY: capture OTP is forbidden in production.")

    server_thread.start()
    try:
        _wait_for_server(server, server_thread)
        _run_console(server, server_thread)
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line entry point for the reproducible ElderCareBD Task 13 workflow."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path


ML_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ML_ROOT.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ml_training.eldercare_ml.training import run_training  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the approved local datasets, evaluate Task 13 candidates, and "
            "write new v2 artifacts without touching legacy models."
        )
    )
    parser.add_argument(
        "--created-at",
        help=(
            "Optional ISO-8601 timestamp recorded in metadata. Supplying one makes report "
            "timestamps deterministic for audited rebuilds."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.created_at:
        try:
            datetime.fromisoformat(args.created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SystemExit(f"Invalid --created-at ISO-8601 timestamp: {exc}") from exc
    run_training(ML_ROOT, created_at=args.created_at)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

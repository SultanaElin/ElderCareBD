"""Command-line entry point for ElderCareBD Task 13C."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


ML_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ML_ROOT.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ml_training.eldercare_ml.kidney_training import run_task13c  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the fixed local kidney dataset, run leakage-safe negative-control "
            "comparisons, and record whether deployment is scientifically defensible."
        )
    )
    parser.add_argument(
        "--created-at",
        help=(
            "Optional ISO-8601 timestamp for the run manifest. Use a fixed value for "
            "a byte-stable audited rebuild."
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
    manifest = run_task13c(ML_ROOT, created_at=args.created_at)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

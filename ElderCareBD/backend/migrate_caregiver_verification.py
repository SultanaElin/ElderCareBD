import argparse
import json

from caregiver_verification_migration import migrate_caregiver_verification


def main():
    parser = argparse.ArgumentParser(
        description="Safely add the Task 15 caregiver OTP verification schema."
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--backup", required=True)
    args = parser.parse_args()

    result = migrate_caregiver_verification(args.database, args.backup)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
